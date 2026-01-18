import argparse
import logging
from pathlib import Path

import pandas as pd

from backend.utils.extract_png import download_png, extract_green_curve_from_png
from backend.utils.time import to_iso_utc

logger = logging.getLogger(__name__)


def _build_plot(df: pd.DataFrame, output_path: Path) -> None:
    try:
        import matplotlib.pyplot as plt
    except ImportError as exc:
        raise RuntimeError("matplotlib is required to generate the debug plot") from exc

    fig, ax = plt.subplots(figsize=(12, 4))
    ax.plot(df["timestamp"], df["value"], label="RAW (picchi reali)", color="#4ade80", linewidth=1)
    ax.plot(df["timestamp"], df["value_smooth"], label="Trend (smoothed)", color="#22d3ee", linewidth=1)
    ax.axhline(2.0, color="#ef4444", linestyle="--", linewidth=1, label="Soglia 2 mV")
    ax.set_yscale("log")
    ax.set_ylabel("mV")
    ax.set_xlabel("UTC")
    ax.set_facecolor("#151821")
    fig.patch.set_facecolor("#151821")
    ax.tick_params(colors="#e6e7ea")
    ax.yaxis.label.set_color("#e6e7ea")
    ax.xaxis.label.set_color("#e6e7ea")
    ax.legend(facecolor="#151821", labelcolor="#e6e7ea")
    fig.tight_layout()
    fig.savefig(output_path, dpi=150)
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser(description="Debug INGV PNG extraction pipeline.")
    parser.add_argument(
        "--url",
        default="https://www.ct.ingv.it/RMS_Etna/2.png",
        help="INGV PNG URL",
    )
    parser.add_argument(
        "--output",
        default="data/ingv_debug_compare.png",
        help="Output PNG path for comparison plot",
    )
    args = parser.parse_args()

    png_bytes, reference_time = download_png(args.url)
    data, metadata = extract_green_curve_from_png(png_bytes, end_time=reference_time)

    df = pd.DataFrame(data)
    if df.empty:
        logger.warning("No data extracted from PNG.")
        return

    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    df = df.sort_values("timestamp")
    df["value_smooth"] = df["value_avg"].rolling(window=9, min_periods=1, center=True).median()

    max_7d = df.loc[df["value"].idxmax()]
    recent_df = df[df["timestamp"] >= df["timestamp"].max() - pd.Timedelta(hours=24)]
    max_24h = recent_df.loc[recent_df["value"].idxmax()] if not recent_df.empty else max_7d

    logger.info("PNG reference end=%s", to_iso_utc(metadata.get("end_time")))
    logger.info("Max 7d: %.4f mV @ %s", max_7d["value"], to_iso_utc(max_7d["timestamp"]))
    logger.info("Max 24h: %.4f mV @ %s", max_24h["value"], to_iso_utc(max_24h["timestamp"]))
    logger.info("Max visible in PNG: %s mV", metadata.get("max_visible_value"))

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    _build_plot(df, output_path)
    logger.info("Debug plot saved to %s", output_path)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
