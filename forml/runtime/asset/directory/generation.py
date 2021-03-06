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

"""Generic assets directory.
"""
import collections
import datetime
import json
import logging
import operator
import types
import typing
import uuid

from forml.io.dsl.struct import kind
from forml.runtime.asset import directory, persistent

if typing.TYPE_CHECKING:
    from forml.runtime.asset.directory import project as prjmod, lineage as lngmod

LOGGER = logging.getLogger(__name__)


class Tag(collections.namedtuple('Tag', 'training, tuning, states')):
    """Generation metadata."""

    class Mode(types.SimpleNamespace):
        """Mode metadata."""

        class Proxy(tuple):
            """Mode attributes proxy."""

            _tag = property(operator.itemgetter(0))
            _mode = property(operator.itemgetter(1))

            def __new__(cls, tag: 'Tag', mode: 'Tag.Mode'):
                return super().__new__(cls, (tag, mode))

            def __repr__(self):
                return f'Mode{repr(self._mode)}'

            def __bool__(self):
                return bool(self._mode)

            def __getattr__(self, item):
                return getattr(self._mode, item)

            def __eq__(self, other) -> bool:
                # pylint: disable=protected-access
                return isinstance(other, self.__class__) and self._mode == other._mode

            def replace(self, **kwargs) -> 'Tag':
                """Mode attributes setter.

                Args:
                    **kwargs: Keyword parameters to be set on given mode attributes.

                Returns:
                    New tag instance with new values.
                """
                mode = self._mode.__class__(**{**self._mode.__dict__, **kwargs})
                return Tag(**{k: mode if v is self._mode else v for k, v in self._tag._asdict().items()})

            def trigger(self, timestamp: typing.Optional[datetime.datetime] = None) -> 'Tag':
                """Create new tag with given mode triggered (all attributes reset and timestamp set to now).

                Returns:
                    New tag.
                """
                return self.replace(timestamp=(timestamp or datetime.datetime.utcnow()))

        def __init__(self, timestamp: typing.Optional[datetime.datetime], **kwargs: typing.Any):
            super().__init__(timestamp=timestamp, **kwargs)

        def __bool__(self):
            return bool(self.timestamp)

    class Training(Mode):
        """Training mode attributes."""

        def __init__(
            self, timestamp: typing.Optional[datetime.datetime] = None, ordinal: typing.Optional[kind.Native] = None
        ):
            super().__init__(timestamp, ordinal=ordinal)

    class Tuning(Mode):
        """Tuning mode attributes."""

        def __init__(self, timestamp: typing.Optional[datetime.datetime] = None, score: typing.Optional[float] = None):
            super().__init__(timestamp, score=score)

    _TSFMT = '%Y-%m-%dT%H:%M:%S.%f'

    def __new__(
        cls,
        training: typing.Optional[Training] = None,
        tuning: typing.Optional[Tuning] = None,
        states: typing.Optional[typing.Sequence[uuid.UUID]] = None,
    ):
        return super().__new__(cls, training or cls.Training(), tuning or cls.Tuning(), tuple(states or []))

    def __bool__(self):
        return bool(self.training or self.tuning)

    def __getattribute__(self, name: str) -> typing.Any:
        attribute = super().__getattribute__(name)
        if isinstance(attribute, Tag.Mode):
            attribute = self.Mode.Proxy(self, attribute)
        return attribute

    def replace(self, **kwargs) -> 'Tag':
        """Replace give non-mode attributes.

        Args:
            **kwargs: Non-mode attributes to be replaced.

        Returns:
            New tag instance.
        """
        if not {k for k, v in self._asdict().items() if not isinstance(v, Tag.Mode)}.issuperset(kwargs.keys()):
            raise ValueError('Invalid replacement')
        return self._replace(**kwargs)

    @classmethod
    def _strftime(cls, timestamp: typing.Optional[datetime.datetime]) -> typing.Optional[str]:
        """Encode the timestamp into string representation.

        Args:
            timestamp: Timestamp to be encoded.

        Returns:
            Timestamp string representation.
        """
        if not timestamp:
            return None
        return timestamp.strftime(cls._TSFMT)

    @classmethod
    def _strptime(cls, raw: typing.Optional[str]) -> typing.Optional[datetime.datetime]:
        """Decode the timestamp from string representation.

        Args:
            raw: Timestamp string representation.

        Returns:
            Timestamp instance.
        """
        if not raw:
            return None
        return datetime.datetime.strptime(raw, cls._TSFMT)

    def dumps(self) -> bytes:
        """Dump the tag into a string of bytes.

        Returns:
            String of bytes representation.
        """
        return json.dumps(
            {
                'training': {'timestamp': self._strftime(self.training.timestamp), 'ordinal': self.training.ordinal},
                'tuning': {'timestamp': self._strftime(self.tuning.timestamp), 'score': self.tuning.score},
                'states': [str(s) for s in self.states],
            },
            indent=4,
        ).encode('utf-8')

    @classmethod
    def loads(cls, raw: bytes) -> 'Tag':
        """Loaded the dumped tag.

        Args:
            raw: Serialized tag representation to be loaded.

        Returns:
            Tag instance.
        """
        meta = json.loads(raw.decode('utf-8'))
        return cls(
            training=cls.Training(
                timestamp=cls._strptime(meta['training']['timestamp']), ordinal=meta['training']['ordinal']
            ),
            tuning=cls.Tuning(timestamp=cls._strptime(meta['tuning']['timestamp']), score=meta['tuning']['score']),
            states=(uuid.UUID(s) for s in meta['states']),
        )


NOTAG = Tag()
TAGS = directory.Cache(persistent.Registry.open)
STATES = directory.Cache(persistent.Registry.read)


# pylint: disable=unsubscriptable-object; https://github.com/PyCQA/pylint/issues/2822
class Level(directory.Level):
    """Snapshot of project states in its particular training iteration."""

    class Key(directory.Level.Key, int):
        """Generation key."""

        MIN = 1

        def __new__(cls, key: typing.Optional[typing.Union[str, int, 'Level.Key']] = MIN):
            try:
                instance = super().__new__(cls, str(key))
            except ValueError as err:
                raise cls.Invalid(f'Invalid key {key} (not an integer)') from err
            if instance < cls.MIN:
                raise cls.Invalid(f'Invalid key {key} (not natural)')
            return instance

        @property
        def next(self) -> 'Level.Key':
            return self.__class__(self + 1)

    def __init__(self, lineage: 'lngmod.Level', key: typing.Optional[typing.Union[str, int, 'Level.Key']] = None):
        super().__init__(key, parent=lineage)

    @property
    def project(self) -> 'prjmod.Level':
        """Get the project of this generation.

        Returns:
            Project of this generation.
        """
        return self.lineage.project

    @property
    def lineage(self) -> 'lngmod.Level':
        """Get the lineage key of this generation.

        Returns:
            Lineage key of this generation.
        """
        return self._parent

    @property
    def tag(self) -> 'Tag':
        """Generation metadata. In case of implicit generation and empty lineage this returns a "null" tag (a Tag object
        with all fields empty).

        Returns:
            Generation tag (metadata) object.
        """
        # project/lineage must exist so let's fetch it outside of try-except
        project = self.project.key
        lineage = self.lineage.key
        try:
            generation = self.key
        except self.Listing.Empty:  # generation doesn't exist
            LOGGER.debug('No previous generations found - using a null tag')
            return NOTAG
        return TAGS(self.registry, project, lineage, generation)

    def list(self) -> directory.Level.Listing:
        """Return the listing of this level.

        Returns:
            Level listing.
        """
        return self.Listing(self.tag.states)

    def get(self, sid: typing.Union[uuid.UUID, int]) -> bytes:
        """Load the state based on provided id or positional index.

        Args:
            sid: Index or absolute id of the state object to be loaded.

        Returns:
            Serialized state.
        """
        if not self.tag.training:
            return bytes()
        if isinstance(sid, int):
            sid = self.tag.states[sid]
        if sid not in self.tag.states:
            raise Level.Invalid(f'Unknown state reference for {self}: {sid}')
        LOGGER.debug('%s: Getting state %s', self, sid)
        return STATES(self.registry, self.project.key, self.lineage.key, self.key, sid)
