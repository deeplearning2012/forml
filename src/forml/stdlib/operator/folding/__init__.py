"""
Folding operator bases.
"""
import abc

from sklearn import model_selection

from forml.flow import task, pipeline
from forml.flow.graph import node
from forml.flow.pipeline import topology
from forml.stdlib.actor import frame


class Crossvalidated(topology.Operator, metaclass=abc.ABCMeta):
    """Generic crossvalidating operator.
    """
    class Builder(metaclass=abc.ABCMeta):
        """Crossvalidation builder used as a folding context.
        """

        @abc.abstractmethod
        def build(self) -> pipeline.Segment:
            """Builder finalize method.

            Returns: Crossvalidation pipeline segment.
            """

    def __init__(self, crossvalidator: model_selection.BaseCrossValidator):
        self.splitter: task.Spec = frame.TrainTestSplit.spec(crossvalidator=crossvalidator)

    @property
    def nsplits(self) -> int:
        """Get the number of folds.

        Returns: Number of folds.
        """
        return self.splitter.kwargs['crossvalidator'].get_n_splits()

    def compose(self, left: topology.Composable) -> pipeline.Segment:
        """Ensemble composition.

        Args:
            left: left segment.

        Returns: Composed segment track.
        """
        head: pipeline.Segment = pipeline.Segment()
        splitter = node.Worker(self.splitter, 1, 2 * self.nsplits)
        splitter.train(head.train.publisher, head.label.publisher)
        features: node.Worker = splitter.fork()
        features[0].subscribe(head.train.publisher)
        labels: node.Worker = splitter.fork()
        labels[0].subscribe(head.label.publisher)

        builder = self.builder(head, left.expand())
        for fold in range(self.nsplits):
            inner: pipeline.Segment = left.expand()
            self.fold(fold, builder, inner, features, labels)

        return builder.build()

    @abc.abstractmethod
    def builder(self, head: pipeline.Segment, inner: pipeline.Segment) -> 'Crossvalidated.Builder':
        """Create a builder (folding context).

        Args:
            head: Head of the crossvalidation segment.
            inner: Exclusive instance of the inner composition.

        Returns: Builder instance.
        """

    @abc.abstractmethod
    def fold(self, fold: int, builder: 'Crossvalidated.Builder', inner: pipeline.Segment,
             features: node.Worker, labels: node.Worker) -> None:
        """Implement composition of single fold.

        Args:
            fold: Fold index.
            builder: Composition builder (folding context).
            inner: Exclusive instance of the inner composition.
            features: Features splitter actor.
            labels: Labels splitter actor.
        """