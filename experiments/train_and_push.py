"""
Train multiple SGDClassifier models on the Iris dataset, log results to MLflow,
push metrics to Prometheus PushGateway, and save the best model locally.
"""

import os
from itertools import product
from typing import List, Tuple

import joblib
from numpy.typing import NDArray
import mlflow
import mlflow.sklearn
from dotenv import load_dotenv
from prometheus_client import CollectorRegistry, Gauge, push_to_gateway
from sklearn.datasets import load_iris
from sklearn.linear_model import SGDClassifier
from sklearn.metrics import accuracy_score, log_loss
from sklearn.model_selection import train_test_split

load_dotenv()

# Configuration
MLFLOW_TRACKING_URI: str = os.getenv("MLFLOW_TRACKING_URI", "http://localhost:5000")
PUSHGATEWAY_URL: str = os.getenv("PUSHGATEWAY_URL", "http://localhost:9091")
EXPERIMENT_NAME: str = "Iris Classification"

LEARNING_RATES: List[float] = [0.001, 0.01, 0.1]
EPOCHS: List[int] = [100, 200, 500]


def push_metrics(
    pushgateway_url: str,
    run_id: str,
    accuracy: float,
    loss: float,
) -> None:
    """Push accuracy and loss metrics for a single MLflow run to PushGateway."""
    registry = CollectorRegistry()
    g_acc = Gauge("mlflow_accuracy", "MLflow run accuracy", ["run_id"], registry=registry)
    g_loss = Gauge("mlflow_loss", "MLflow run loss", ["run_id"], registry=registry)
    g_acc.labels(run_id=run_id).set(accuracy)
    g_loss.labels(run_id=run_id).set(loss)
    push_to_gateway(
        pushgateway_url,
        job="mlflow_training",
        grouping_key={"run_id": run_id},
        registry=registry,
    )


def train_and_log(
    X_train: NDArray,
    X_test: NDArray,
    y_train: NDArray,
    y_test: NDArray,
    learning_rate: float,
    epochs: int,
    run_number: int,
    pushgateway_url: str,
) -> None:
    """Train one SGDClassifier, log to MLflow, and push metrics to PushGateway."""
    with mlflow.start_run():
        # Parameters
        mlflow.log_param("learning_rate", learning_rate)
        mlflow.log_param("epochs", epochs)

        # Train
        model = SGDClassifier(
            loss="log_loss",
            learning_rate="constant",
            eta0=learning_rate,
            max_iter=epochs,
            random_state=42,
        )
        model.fit(X_train, y_train)

        # Metrics
        accuracy: float = accuracy_score(y_test, model.predict(X_test))
        loss: float = log_loss(y_test, model.predict_proba(X_test))

        mlflow.log_metric("accuracy", accuracy)
        mlflow.log_metric("loss", loss)

        # Artifact
        mlflow.sklearn.log_model(model, "model")

        # PushGateway
        run_id: str = mlflow.active_run().info.run_id  # type: ignore[union-attr]
        push_metrics(pushgateway_url, run_id, accuracy, loss)

        print(
            f"Run {run_number:2d} | lr={learning_rate:.3f} | epochs={epochs:3d} "
            f"| accuracy={accuracy:.4f} | loss={loss:.4f} | run_id={run_id}"
        )


def save_best_model(best_run_id: str, best_accuracy: float, best_loss: float) -> None:
    """Load the best model from MLflow and persist it locally under best_model/."""
    os.makedirs("best_model", exist_ok=True)

    model = mlflow.sklearn.load_model(f"runs:/{best_run_id}/model")
    joblib.dump(model, "best_model/model.joblib")

    with open("best_model/run_info.txt", "w") as fh:
        fh.write(f"run_id={best_run_id}\n")
        fh.write(f"accuracy={best_accuracy}\n")
        fh.write(f"loss={best_loss}\n")

    print(f"\nBest model saved to best_model/model.joblib")
    print(f"  run_id   : {best_run_id}")
    print(f"  accuracy : {best_accuracy:.4f}")
    print(f"  loss     : {best_loss:.4f}")


def main() -> None:
    # MLflow setup
    mlflow.set_tracking_uri(MLFLOW_TRACKING_URI)
    mlflow.set_experiment(EXPERIMENT_NAME)

    # Data
    X, y = load_iris(return_X_y=True)
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=42
    )

    # Grid search
    param_grid: List[Tuple[float, int]] = list(product(LEARNING_RATES, EPOCHS))
    print(f"Starting {len(param_grid)} experiments — {EXPERIMENT_NAME}")
    print("-" * 80)

    for run_number, (lr, ep) in enumerate(param_grid, start=1):
        train_and_log(
            X_train=X_train,
            X_test=X_test,
            y_train=y_train,
            y_test=y_test,
            learning_rate=lr,
            epochs=ep,
            run_number=run_number,
            pushgateway_url=PUSHGATEWAY_URL,
        )

    # Find best run
    best_runs = mlflow.search_runs(
        experiment_names=[EXPERIMENT_NAME],
        order_by=["metrics.accuracy DESC"],
        max_results=1,
    )
    best_run_id: str = best_runs.iloc[0]["run_id"]
    best_accuracy: float = best_runs.iloc[0]["metrics.accuracy"]
    best_loss: float = best_runs.iloc[0]["metrics.loss"]

    print("-" * 80)
    print(f"\nBest run: run_id={best_run_id} | accuracy={best_accuracy:.4f}")

    save_best_model(best_run_id, best_accuracy, best_loss)


if __name__ == "__main__":
    main()
