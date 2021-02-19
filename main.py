import os
from datetime import datetime
from typing import Any, Generator, Mapping, Tuple

import dataget

import jax
import jax.numpy as jnp
import matplotlib.pyplot as plt
import numpy as np
from tensorboardX.writer import SummaryWriter
import typer
import optax
import einops

import elegy


class ViT(elegy.Module):
    """Standard LeNet-300-100 MLP network."""

    def __init__(
        self,
        size: int,
        num_layers: int,
        num_heads: int,
        dropout: float,
        use_conv: bool = False,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.size = size
        self.num_layers = num_layers
        self.num_heads = num_heads
        self.dropout = dropout
        self.use_conv = use_conv

    def call(self, x: jnp.ndarray):
        x = x.astype(jnp.float32) / 255.0

        if self.use_conv:
            x = x[..., None]
            x = elegy.nn.Conv2D(self.size, [7, 7], stride=4, padding="valid")(x)
            x = einops.rearrange(x, "batch h w d -> batch (h w) d")
        else:
            x = einops.rearrange(
                x, "batch (h1 h2) (w1 w2) -> batch (h1 w1) (h2 w2)", h1=4, w1=4
            )
            x = elegy.nn.Linear(self.size)(x)

        # zeros is the predict token padding
        zeros = jnp.zeros(shape=[x.shape[0], 1, x.shape[-1]])

        x = jnp.concatenate([zeros, x], axis=1)

        positional_embeddings = self.add_parameter(
            "positional_embeddings",
            lambda: elegy.initializers.TruncatedNormal()(x.shape[-2:], jnp.float32),
        )

        positional_embeddings = einops.repeat(
            positional_embeddings,
            "... -> batch ...",
            batch=x.shape[0],
        )

        x = x + positional_embeddings

        x = elegy.nn.transformers.TransformerEncoder(
            lambda: elegy.nn.transformers.TransformerEncoderLayer(
                head_size=self.size,
                num_heads=self.num_heads,
                dropout=self.dropout,
            ),
            num_layers=self.num_layers,
        )(x)

        x = x[:, 0]

        logits = elegy.nn.Linear(10)(x)

        return logits


def main(
    debug: bool = False,
    eager: bool = False,
    logdir: str = "runs",
    steps_per_epoch: int = 200,
    batch_size: int = 64,
    epochs: int = 100,
    size: int = 32,
    num_layers: int = 3,
    num_heads: int = 8,
    dropout: float = 0.0,
    use_conv: bool = False,
):

    if debug:
        import debugpy

        print("Waiting for debugger...")
        debugpy.listen(5678)
        debugpy.wait_for_client()

    current_time = datetime.now().strftime("%b%d_%H-%M-%S")
    logdir = os.path.join(logdir, current_time)

    X_train, y_train, X_test, y_test = dataget.image.mnist(global_cache=True).get()

    print("X_train:", X_train.shape, X_train.dtype)
    print("y_train:", y_train.shape, y_train.dtype)
    print("X_test:", X_test.shape, X_test.dtype)
    print("y_test:", y_test.shape, y_test.dtype)

    model = elegy.Model(
        module=ViT(
            size=size,
            num_layers=num_layers,
            num_heads=num_heads,
            dropout=dropout,
            use_conv=use_conv,
        ),
        loss=[
            elegy.losses.SparseCategoricalCrossentropy(from_logits=True),
            # elegy.regularizers.GlobalL2(l=1e-4),
        ],
        metrics=elegy.metrics.SparseCategoricalAccuracy(),
        optimizer=optax.adamw(1e-3),
        run_eagerly=eager,
    )

    model.init(X_train, y_train)

    model.summary(X_train[:64])

    history = model.fit(
        x=X_train,
        y=y_train,
        epochs=epochs,
        steps_per_epoch=steps_per_epoch,
        batch_size=batch_size,
        validation_data=(X_test, y_test),
        shuffle=True,
        callbacks=[elegy.callbacks.TensorBoard(logdir=logdir)],
    )

    elegy.utils.plot_history(history)

    # get random samples
    idxs = np.random.randint(0, 10000, size=(9,))
    x_sample = X_test[idxs]

    # get predictions
    y_pred = model.predict(x=x_sample)

    # plot and save results
    with SummaryWriter(os.path.join(logdir, "val")) as tbwriter:
        figure = plt.figure(figsize=(12, 12))
        for i in range(3):
            for j in range(3):
                k = 3 * i + j
                plt.subplot(3, 3, k + 1)
                plt.title(f"{np.argmax(y_pred[k])}")
                plt.imshow(x_sample[k], cmap="gray")
        # tbwriter.add_figure("Predictions", figure, 100)

    plt.show()

    print(
        "\n\n\nMetrics and images can be explored using tensorboard using:",
        f"\n \t\t\t tensorboard --logdir {logdir}",
    )


if __name__ == "__main__":
    typer.run(main)
