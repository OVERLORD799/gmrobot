#!/usr/bin/env python3
"""Plot EE trajectory from a _steps.csv file. Usage: plot_trajectory.py <steps.csv>"""
import csv
import sys


def plot(path):
    try:
        import matplotlib.pyplot as plt
    except ImportError:
        sys.exit("matplotlib not installed. Run: pip install matplotlib")

    try:
        with open(path, newline="") as f:
            rows = list(csv.DictReader(f))
    except FileNotFoundError:
        sys.exit(f"ERROR: file not found: {path}")
    if not rows:
        sys.exit("ERROR: empty CSV")

    ee_x = [float(r["ee_x"]) for r in rows]
    ee_y = [float(r["ee_y"]) for r in rows]
    ee_z = [float(r["ee_z"]) for r in rows]
    colors = {"ALLOW": "green", "SLOW": "yellow", "SLOW_DOWN": "yellow",
              "STOP": "red"}
    c = [colors.get(r.get("gate", ""), "gray") for r in rows]

    fig = plt.figure(figsize=(10, 7))
    ax = fig.add_subplot(projection="3d")
    ax.scatter(ee_x, ee_y, ee_z, c=c, s=4, alpha=0.7, label="EE trajectory")
    ax.scatter([float(r["hand_x"]) for r in rows],
               [float(r["hand_y"]) for r in rows],
               [float(r["hand_z"]) for r in rows],
               c="blue", s=1, alpha=0.4, label="hand surface")

    ax.set_xlabel("X (m)"); ax.set_ylabel("Y (m)"); ax.set_zlabel("Z (m)")
    ax.set_title(f"EE Trajectory — {path}")
    ax.legend(markerscale=3)

    out = path + "_trajectory.png"
    fig.savefig(out, dpi=150, bbox_inches="tight")
    print(f"Saved: {out}")
    plt.close(fig)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit("Usage: plot_trajectory.py <steps.csv>")
    plot(sys.argv[1])
