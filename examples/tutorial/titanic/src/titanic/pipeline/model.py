"""
Pipeline models.

This module is informal from ForML perspective and has been created just for structuring the project code base.

Here we just create couple of forml operators that implement particular classifier.
"""

from sklearn import ensemble as estimator
from sklearn import linear_model

from forml.stdlib.actor import wrapped
from forml.stdlib.operator import simple

# Defining a forml operator by wrapping the standard sklearn classifier
RFC = simple.Consumer.operator(wrapped.Class.actor(
    estimator.RandomForestClassifier, train='fit', apply='predict_proba'))

# Defining a forml operator by wrapping the standard sklearn classifier
GBC = simple.Consumer.operator(wrapped.Class.actor(
    estimator.GradientBoostingClassifier, train='fit', apply='predict_proba'))

# Defining a forml operator by wrapping the standard sklearn classifier
LR = simple.Consumer.operator(wrapped.Class.actor(linear_model.LogisticRegression, train='fit', apply='predict_proba'))