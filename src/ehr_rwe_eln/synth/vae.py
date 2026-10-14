"""A variational autoencoder (VAE) trained with differential privacy, as a second synthesizer.

A VAE is two small neural networks. The encoder compresses each person's record into a few
numbers (the latent code); the decoder rebuilds the record from them. Training rewards accurate
rebuilds and keeps the latent codes close to a standard normal distribution, so that afterwards
random normal draws, decoded, give new records.

Training is private through DP-SGD (Opacus): each step clips every person's gradient to a fixed
length, so no one person can move the model far, then adds Gaussian noise to the sum. Opacus
picks the noise level that reaches the target epsilon over the planned steps and reports what
was spent. The guarantee is (epsilon, delta), delta being a small chance it does not hold.

Records are encoded as the Bayesian network encodes them (the spec's bins and categories), one
hot per column, so comparisons between the two synthesizers measure the models, not the
preprocessing. The row count is noisy, from 1% of the budget, as in the Bayesian network.
"""

import sys
import warnings

import numpy as np
import pandas as pd
import torch
from diffprivlib.mechanisms import GeometricTruncated
from opacus import PrivacyEngine
from torch import nn
from torch.nn import functional as F
from torch.utils.data import DataLoader, TensorDataset

from ehr_rwe_eln.synth.bayes_net import decode, encode
from ehr_rwe_eln.synth.spec import Release, Spec

COUNT_SHARE = 0.01


class TabularVAE(nn.Module):
    def __init__(self, sizes: list[int], hidden: int, latent: int):
        super().__init__()
        self.sizes = sizes
        width = sum(sizes)
        self.encoder = nn.Sequential(
            nn.Linear(width, hidden), nn.ReLU(), nn.Linear(hidden, hidden), nn.ReLU()
        )
        self.mean = nn.Linear(hidden, latent)
        self.log_variance = nn.Linear(hidden, latent)
        self.decoder = nn.Sequential(
            nn.Linear(latent, hidden), nn.ReLU(), nn.Linear(hidden, hidden), nn.ReLU(),
            nn.Linear(hidden, width),
        )  # fmt: skip

    def forward(self, x: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
        h = self.encoder(x)
        mean, log_variance = self.mean(h), self.log_variance(h)
        # The reparameterization trick: sample the code as mean plus scaled noise, so gradients
        # flow through mean and variance.
        z = mean + torch.exp(0.5 * log_variance) * torch.randn_like(mean)
        return self.decoder(z), mean, log_variance


def _loss(
    model: TabularVAE, logits: torch.Tensor, codes: torch.Tensor, mean, log_variance
) -> torch.Tensor:
    """Rebuild error (cross-entropy per column, summed) plus the KL divergence that pulls the
    latent codes toward a standard normal, averaged over the batch."""
    rebuild, start = 0, 0
    for j, size in enumerate(model.sizes):
        rebuild = rebuild + F.cross_entropy(
            logits[:, start : start + size], codes[:, j], reduction="none"
        )
        start += size
    kl = -0.5 * (1 + log_variance - mean.pow(2) - log_variance.exp()).sum(dim=1)
    return (rebuild + kl).mean()


def synthesize(table: pd.DataFrame, spec: Spec, release: Release) -> tuple[pd.DataFrame, list]:
    """A synthetic table and the privacy it spent: the noisy row count, then DP-SGD."""
    settings, columns = spec.vae, spec.columns
    sizes = [c.size for c in columns]
    codes = encode(table, columns)
    if spec.seed is not None:
        torch.manual_seed(spec.seed)
    noise = np.random.RandomState(spec.seed) if spec.seed is not None else None
    sampling = np.random.default_rng(spec.seed)

    count_epsilon = release.epsilon * COUNT_SHARE
    count = GeometricTruncated(
        epsilon=count_epsilon, sensitivity=1, lower=0, upper=sys.maxsize, random_state=noise
    )
    n = int(count.randomise(len(table)))

    codes_t = torch.as_tensor(codes)
    one_hot = torch.cat(
        [F.one_hot(codes_t[:, j], size).float() for j, size in enumerate(sizes)], dim=1
    )
    loader = DataLoader(TensorDataset(one_hot, codes_t), batch_size=settings.batch_size)
    model = TabularVAE(sizes, settings.hidden, settings.latent)
    optimizer = torch.optim.Adam(model.parameters(), lr=settings.learning_rate)
    with warnings.catch_warnings():
        # Three known Opacus notices: secure_mode is off (the spec's seed note covers that), the
        # accountant's search hit its largest order (the reported epsilon is still an upper
        # bound), and backward hooks fire with no input gradients (inputs are data, not weights).
        for message in ("Secure RNG turned off", "Optimal order is the largest alpha",
                        "Full backward hook is firing"):  # fmt: skip
            warnings.filterwarnings("ignore", message=f".*{message}.*")
        # secure_mode draws noise from a cryptographic generator; seeded runs on synthetic
        # sources skip it so they can be remade. A run on real data needs it on, which the spec
        # refuses here (see Spec: torchcsprng does not install on this stack). The RDP
        # accountant's epsilon is a guaranteed upper bound; the default (PRV) is tighter but
        # rests on numerical integration, which warned of divergence on this data.
        engine = PrivacyEngine(accountant="rdp", secure_mode=False)
        private_model, optimizer, loader = engine.make_private_with_epsilon(
            module=model,
            optimizer=optimizer,
            data_loader=loader,
            target_epsilon=release.epsilon - count_epsilon,
            target_delta=settings.delta,
            epochs=settings.epochs,
            max_grad_norm=settings.max_grad_norm,
        )
        private_model.train()
        steps = 0
        for _ in range(settings.epochs):
            for x, y in loader:
                if len(x) == 0:  # Poisson sampling can draw an empty batch
                    continue
                optimizer.zero_grad()
                logits, mean, log_variance = private_model(x)
                _loss(model, logits, y, mean, log_variance).backward()
                optimizer.step()
                steps += 1
        spent = float(engine.get_epsilon(settings.delta))

    model.eval()
    with torch.no_grad():
        logits = model.decoder(torch.randn(n, settings.latent))
    synthetic, start = np.empty((n, len(columns)), dtype=np.int64), 0
    for j, size in enumerate(sizes):
        p = torch.softmax(logits[:, start : start + size], dim=1).numpy().astype(float)
        cumulative = p.cumsum(axis=1)
        synthetic[:, j] = np.minimum((cumulative < sampling.random((n, 1))).sum(axis=1), size - 1)
        start += size

    spend = [
        {"mechanism": "geometric", "of": "row count", "epsilon": count_epsilon},
        {
            "mechanism": "dp_sgd",
            "epsilon": spent,
            "delta": settings.delta,
            "noise_multiplier": float(optimizer.noise_multiplier),
            "max_grad_norm": settings.max_grad_norm,
            "sample_rate": float(loader.sample_rate),
            "steps": steps,
            "epochs": settings.epochs,
        },
    ]
    return decode(synthetic, columns, sampling), spend
