# Licensed to the Apache Software Foundation (ASF) under one
# or more contributor license agreements.  See the NOTICE file
# distributed with this work for additional information
# regarding copyright ownership.  The ASF licenses this file
# to you under the Apache License, Version 2.0 (the
# "License"); you may not use this file except in compliance
# with the License.  You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing,
# software distributed under the License is distributed on an
# "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
# KIND, either express or implied.  See the License for the
# specific language governing permissions and limitations
# under the License.

"""
DSL parser to ANSI SQL.
"""
import logging
import re
import typing

from forml.io.dsl import parser as parsmod, function, error
from forml.io.dsl.schema import series, frame, kind as kindmod

LOGGER = logging.getLogger(__name__)


class Parser(parsmod.Bundle[str]):
    """DSL parser producing an ANSI SQL select statements.
    """

    class Expression:
        """Expression generator/formatter.
        """
        ASSOCIATIVE = re.compile(r"\s*(?:(\S*\()?\s*[^-+*/%\s]+\s*(?(1).*\))|TIMESTAMP *'.+'|DATE *'.+')\s*")

        def __init__(self, template: str, mapper: typing.Optional[
                typing.Callable[..., typing.Sequence]] = None):
            self._template: str = template
            self._mapper: typing.Optional[typing.Callable[..., typing.Sequence]] = mapper

        def __call__(self, *args: typing.Any) -> str:
            """Actual expression generator.

            Args:
                *args: Expression arguments.

            Returns: Generated expression value.
            """

            def clean(arg: str) -> str:
                """Add parentheses if necessary.

                Args:
                    arg: Argument to be cleaned.

                Returns: Clean argument.
                """
                if not self.ASSOCIATIVE.fullmatch(arg):
                    arg = f'({arg})'
                return arg

            if self._mapper:
                args = self._mapper(*args)
            args = [clean(a) for a in args]
            return self._template.format(*args)

    KIND: typing.Mapping[kindmod.Any, str] = {
        kindmod.Boolean(): 'BOOLEAN',
        kindmod.Integer(): 'BIGINT',
        kindmod.Float(): 'DOUBLE',
        kindmod.Decimal(): 'DECIMAL',
        kindmod.String(): 'VARCHAR',
        kindmod.Date(): 'DATE',
        kindmod.Timestamp(): 'TIMESTAMP'
    }

    EXPRESSION: typing.Mapping[typing.Type[series.Expression], typing.Callable[..., str]] = {
        function.Addition: Expression('{} + {}'),
        function.Subtraction: Expression('{} - {}'),
        function.Multiplication: Expression('{} * {}'),
        function.Division: Expression('{} / {}'),
        function.Modulus: Expression('{} % {}'),
        function.LessThan: Expression('{} < {}'),
        function.LessEqual: Expression('{} <= {}'),
        function.GreaterThan: Expression('{} > {}'),
        function.GreaterEqual: Expression('{} >= {}'),
        function.Equal: Expression('{} = {}'),
        function.NotEqual: Expression('{} != {}'),
        function.IsNull: Expression('{} IS NULL'),
        function.NotNull: Expression('{} IS NOT NULL'),
        function.And: Expression('{} AND {}'),
        function.Or: Expression('{} OR {}'),
        function.Not: Expression('NOT {}'),
        function.Cast: Expression('cast({} AS {})', lambda _, k: [_, Parser.KIND[k]]),
        function.Count: Expression('count({})', lambda c=None: [c if c is not None else '*'])
    }

    JOIN: typing.Mapping[frame.Join.Kind, str] = {
        frame.Join.Kind.LEFT: 'LEFT',
        frame.Join.Kind.RIGHT: 'RIGHT',
        frame.Join.Kind.INNER: 'INNER',
        frame.Join.Kind.FULL: 'FULL',
        frame.Join.Kind.CROSS: 'CROSS'
    }

    SET: typing.Mapping[frame.Set.Kind, str] = {
        frame.Set.Kind.UNION: 'UNION',
        frame.Set.Kind.INTERSECTION: 'INTERSECT',
        frame.Set.Kind.DIFFERENCE: 'EXCEPT'
    }

    ORDER: typing.Mapping[frame.Ordering.Direction, str] = {
        frame.Ordering.Direction.ASCENDING: 'ASC',
        frame.Ordering.Direction.DESCENDING: 'DESC'
    }

    DATE = '%Y-%m-%d'
    TIMESTAMP = '%Y-%m-%d %H:%M:%S.%f'

    def generate_alias(self, column: str, alias: str) -> str:  # pylint: disable=no-self-use
        """Generate column alias code.

        Args:
            column: Column value.
            alias: Alias to be used for given column.

        Returns: Aliased column.
        """
        return f'{column} AS {alias}'

    def generate_literal(self, literal: series.Literal) -> str:
        """Generate a literal value.

        Args:
            literal: Literal value instance.

        Returns: Literal.
        """
        if isinstance(literal.kind, kindmod.String):
            return f"'{literal.value}'"
        if isinstance(literal.kind, kindmod.Numeric):
            return f'{literal.value}'
        if isinstance(literal.kind, kindmod.Timestamp):
            return f"TIMESTAMP '{literal.value.strftime(self.TIMESTAMP)}'"
        if isinstance(literal.kind, kindmod.Date):
            return f"DATE '{literal.value.strftime(self.DATE)}'"
        if isinstance(literal.kind, kindmod.Array):
            return f"ARRAY[{', '.join(self.generate_literal(v) for v in literal.value)}]"
        raise error.Unsupported(f'Unsupported literal kind: {literal.kind}')

    def generate_expression(self, expression: typing.Type[series.Expression],
                            arguments: typing.Sequence[str]) -> str:
        """Expression of given arguments.

        Args:
            expression: Operator or function implementing the expression.
            arguments: Expression arguments.

        Returns: Expression.
        """
        try:
            return self.EXPRESSION[expression](*arguments)
        except KeyError as err:
            raise error.Unsupported(f'Unsupported expression: {expression}') from err

    def generate_join(self, left: str, right: str, condition: str, kind: frame.Join.Kind) -> str:
        """Generate target code for a join operation using the left/right terms, condition and a join type.

        Args:
            left: Left side of the join pair.
            right: Right side of the join pair.
            condition: Join condition.
            kind: Join type.

        Returns: Join operation.
        """
        return f'{left} {self.JOIN[kind]} JOIN {right} ON {condition}'

    def generate_set(self, left: str, right: str, kind: frame.Set.Kind) -> str:
        """Generate target code for a set operation using the left/right terms, given a set type.

        Args:
            left: Left side of the set pair.
            right: Right side of the set pair.
            kind: Set type.

        Returns: Set operation.
        """
        return f'{left} {self.SET[kind]} {right}'

    def generate_query(self, source: str, columns: typing.Sequence[str],  # pylint: disable=no-self-use
                       where: typing.Optional[str],
                       groupby: typing.Sequence[str], having: typing.Optional[str],
                       orderby: typing.Sequence[str], rows: typing.Optional[frame.Rows]) -> str:
        """Generate query statement code.

        Args:
            source: Source.
            columns: Sequence of selected columns.
            where: Where condition.
            groupby: Sequence of grouping specifiers.
            having: Having condition.
            orderby: Sequence of ordering specifiers.
            rows: Limit spec tuple.

        Returns: Query.
        """
        assert columns, 'Expecting columns'
        query = f'SELECT {", ".join(columns)}\nFROM {source}'
        if where:
            query += f'\nWHERE {where}'
        if groupby:
            query += f'\nGROUP BY {", ".join(groupby)}'
        if having:
            query += f'\nHAVING {having}'
        if orderby:
            query += f'\nORDER BY {", ".join(orderby)}'
        if rows:
            query += '\nLIMIT'
            if rows.offset:
                query += f' {rows.offset},'
            query += f' {rows.count}'
        return query

    def generate_ordering(self, column: str, direction: frame.Ordering.Direction) -> str:
        """Generate column ordering.

        Args:
            column: Column value.
            direction: Ordering direction spec.

        Returns: Column ordering.
        """
        return f'{column} {self.ORDER[direction]}'