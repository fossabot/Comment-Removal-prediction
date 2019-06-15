import logging
import os
import numpy as np

from comment_removal.utils import (timeit,
                                   configure_colored_logging)
from comment_removal.utils.loaders import read_csv
from comment_removal.utils.plotting import plot_training
from comment_removal.encoders import LaserEncoder, LSIEncoder


logger = logging.getLogger(__name__)


def save_model(args, clf):
    from sklearn.externals import joblib

    save_path = os.path.join(
        args.workdir, "{}_{}.pkl".format(args.clf_save_name, args.clf_type))
    joblib.dump(clf, save_path)


def load_model(args):
    from sklearn.externals import joblib

    save_path = os.path.join(
        args.workdir, "{}_{}.pkl".format(args.clf_save_name, args.clf_type))
    return joblib.load(save_path)


@timeit
def make_classifier_and_predict(args, train_set, test_set,
                                target_names, random_seed,
                                clf_name="randomforest"):
    # Data
    x_train, y_train = train_set
    x_test, y_test = test_set

    logger.debug("x-train: {} | "
                 "y-train: {}".format(x_train.shape, y_train.shape))
    logger.debug("x-test: {} | "
                 "y-test: {}".format(x_test.shape, y_test.shape))
    logger.debug("Target names: {}".format(target_names))

    # Out-of-the-box Classifiers
    if clf_name == "randomforest":
        from sklearn.ensemble import RandomForestClassifier
        clf = RandomForestClassifier(max_depth=100, n_estimators=1000,
                                     max_features=100,
                                     n_jobs=8, random_state=random_seed,
                                     verbose=True)
    elif clf_name == "svc":
        from sklearn.svm import SVC
        clf = SVC(gamma='auto', random_state=random_seed, verbose=True)

    elif clf_name == "mlp":
        from sklearn.neural_network import MLPClassifier
        clf = MLPClassifier(hidden_layer_sizes=(512, 128),
                            activation='relu',
                            early_stopping=True,
                            random_state=random_seed)

    # Plot training curves vs data usage
    # plot_training(clf, x_train, y_train)

    # Train the classifier & save
    clf.fit(x_train, y_train)
    save_model(args, clf)
    eval_model(args, clf, x_test, y_test, target_names)
    return clf


@timeit
def encode_text(args, comments):
    """ Applies text preprocesing and LASER encodes the
    comment entries.
    """
    try:

        # encode Comment data
        if args.encoder_type == 'LASER':
            encoder = LaserEncoder(args)
            encoded_comments = encoder.encode(comments,
                                              parallel=args.parallel)
        elif args.encoder_type == 'LSI':
            encoder = LSIEncoder(keep_n=10000)
            encoded_comments = encoder.fit_transform(comments)

        logger.info("Comments encoded: {}".format(encoded_comments.shape))
        return encoded_comments

    except Exception as e:
        logger.error("Error while encoding inputs!")
        raise e


def load_encoded_inputs(training_mat_path, test_mat_path):
    """Loads from file train and test numpy matrices of encoded inputs
    (N x 1024) each.
    Where N is the number of training or testing samples.

    Args:
        training_mat_path (str): train encoded inputs matrix file path
        test_mat_path (str): test encoded inputs matrix file path
    """
    try:
        logger.info("Loading encoded training matrix"
                    " from: {}".format(training_mat_path))
        train_data_encoded = np.load(training_mat_path)

        logger.info("Loading encoded test matrix"
                    " from: {}".format(test_mat_path))
        test_data_encoded = np.load(test_mat_path)

        return train_data_encoded, test_data_encoded
    except Exception as e:
        logger.error("Error loading encoded inputs as numpy file")
        logger.exception(e)


@timeit
def encode_or_load_data(args, data_loader):
    """Encodes or loads the Stance dataset

    Args:
        args ([type]): [description]
        data_loader ([type]): [description]

    Returns:
        [type]: [description]
    """
    # ** Inputs **
    tinp_file = "{}_{}-comments.npy"

    encoded_train_inputs_path = os.path.join(
        args.workdir, tinp_file.format('training', args.encoder_type))
    encoded_test_inputs_path = os.path.join(
        args.workdir, tinp_file.format('test', args.encoder_type))

    # ** Inputs **
    encoded_test_inputs = []
    encoded_training_inputs = []
    if not os.path.exists(encoded_train_inputs_path) or \
            not os.path.exists(encoded_test_inputs_path):

        # Transform and save if not present
        if not os.path.exists(encoded_train_inputs_path):
            logger.info("Encoding train inputs")
            try:
                # Preprocess and encode the inputs
                encoded_training_inputs = encode_text(
                    args,
                    data_loader.get('BODY', set='train')
                )
            except Exception as e:
                logger.error("Error while encoding train dataset")
                logger.exception(e)
            else:
                np.save(encoded_train_inputs_path, encoded_training_inputs)

        if not os.path.exists(encoded_test_inputs_path):
            logger.info("Encoding test inputs")
            try:
                encoded_test_inputs = encode_text(
                    args,
                    data_loader.get('BODY', set='test')
                )
            except Exception as e:
                logger.error("Error while encoding test dataset")
                logger.exception(e)
            else:
                np.save(encoded_test_inputs_path, encoded_test_inputs)

    else:
        logger.info("Loading train & test inputs from file")
        encoded_training_inputs, encoded_test_inputs = \
            load_encoded_inputs(encoded_train_inputs_path,
                                encoded_test_inputs_path)

    # ** Outputs **
    train_outputs = np.array(
        data_loader.get('REMOVED', set='train'))
    test_outputs = np.array(
        data_loader.get('REMOVED', set='test'))

    return ((encoded_training_inputs, train_outputs),
            (encoded_test_inputs, test_outputs))


def save_predictions(args, y_pred):
    import copy

    gold = read_csv(args.test_file)[['BODY', 'REMOVED']]
    pred = copy.deepcopy(gold)

    for i, y_lbl in enumerate(y_pred):
        pred.iloc[i]['Prediction'] = y_lbl

    pred.to_csv(args.predictions_file,
                sep='\t', index=True, index_label='ID')


def roc_curve(y_test, y_score, n_classes=2):
    from sklearn.metrics import roc_auc_score, roc_curve, auc
    from comment_removal.utils.plotting import plot_roc

    y_test_ = np.zeros((y_test.shape[0], 2))
    y_test_[y_test] = 1

    roc_score = roc_auc_score(y_test, np.max(y_score, axis=1))
    logger.info("ROC AUC score: {}".format(roc_score))

    # Compute ROC curve and ROC area for each class
    fpr = {}
    tpr = {}
    roc_auc = {}
    for i in range(n_classes):
        fpr[i], tpr[i], _ = roc_curve(y_test_[:, i], y_score[:, i])
        roc_auc[i] = auc(fpr[i], tpr[i])

    # Compute micro-average ROC curve and ROC area
    fpr["micro"], tpr["micro"], _ = roc_curve(y_test_.ravel(), y_score.ravel())
    roc_auc["micro"] = auc(fpr["micro"], tpr["micro"])

    plot_roc(fpr, tpr, roc_auc, cls=2)




@timeit
def eval_model(args, clf, x_test, y_test, target_names):
    from sklearn.metrics import classification_report

    y_pred = clf.predict(x_test)
    logger.debug("Predictions: {}".format(y_pred.shape))

    # Calculate score and clasificatin report
    score = clf.score(x_test, y_test)
    logger.info("Test score: {}".format(score))
    print(classification_report(y_test, y_pred, target_names=target_names))

    # ROC metrics
    y_score = clf.predict_proba(x_test)
    roc_curve(y_test, y_score)

    # Save predictions as csv
    save_predictions(args, y_pred)
