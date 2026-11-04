"""Génère une LUT .cube S-Log3 / S-Gamut3 -> Rec.709 (formules publiées par Sony).

Chaîne : S-Log3 -> linéaire (réflectance), S-Gamut3 -> XYZ D65 -> Rec.709 linéaire,
épaule douce pour garder les hautes lumières, puis courbe d'affichage BT.1886 (gamma 2,4).
Usage : .venv/bin/python pipeline/make_slog3_lut.py pipeline/luts/slog3-sgamut3-to-rec709.cube
"""
import sys
import numpy as np

N = 33

def slog3_to_linear(x):
    x = np.asarray(x, dtype=np.float64)
    hi = (10.0 ** ((x * 1023.0 - 420.0) / 261.5)) * (0.18 + 0.01) - 0.01
    lo = (x * 1023.0 - 95.0) * 0.01125000 / (171.2102946929 - 95.0)
    return np.where(x >= 171.2102946929 / 1023.0, hi, lo)

def rgb_to_xyz_matrix(prim, white):
    """Matrice RVB -> XYZ à partir des primaires (xy) et du blanc (xy)."""
    xy = np.array(prim, dtype=np.float64)
    P = np.vstack([xy[:, 0], xy[:, 1], 1 - xy[:, 0] - xy[:, 1]]) / xy[:, 1]
    W = np.array([white[0] / white[1], 1.0, (1 - white[0] - white[1]) / white[1]])
    S = np.linalg.solve(P, W)
    return P * S

D65 = (0.3127, 0.3290)
# Primaires publiées par Sony (S-Gamut3 = mêmes primaires que S-Gamut)
SG3_TO_XYZ = rgb_to_xyz_matrix([(0.730, 0.280), (0.140, 0.855), (0.100, -0.050)], D65)
SG3CINE_TO_XYZ = rgb_to_xyz_matrix([(0.766, 0.275), (0.225, 0.800), (0.089, -0.087)], D65)
# XYZ (D65) -> Rec.709 linéaire
XYZ_TO_709 = np.array([
    [3.2404542, -1.5371385, -0.4985314],
    [-0.9692660, 1.8760108, 0.0415560],
    [0.0556434, -0.2040259, 1.0572252],
])

def shoulder(y, knee=0.70, white=2.4):
    """Au-dessus du genou, compresse doucement jusqu'à `white` (linéaire) -> 1,0."""
    y = np.asarray(y, dtype=np.float64)
    over = y > knee
    span = white - knee
    t = np.clip((y - knee) / span, 0.0, None)
    comp = knee + (1.0 - knee) * (1.0 - np.exp(-t * 2.2)) / (1.0 - np.exp(-2.2))
    return np.where(over, comp, y)

def bt1886_encode(y):
    return np.clip(y, 0.0, 1.0) ** (1.0 / 2.4)

def main(out):
    g = np.linspace(0.0, 1.0, N)
    # Ordre .cube : R varie le plus vite, puis G, puis B
    b, gg, r = np.meshgrid(g, g, g, indexing="ij")
    rgb = np.stack([r, gg, b], axis=-1).reshape(-1, 3)
    lin = slog3_to_linear(rgb)
    lin = lin @ (XYZ_TO_709 @ SG3_TO_XYZ).T
    # Exposition : S-Log3 place le gris 18 % à 0,18 linéaire ; on garde tel quel.
    lin = shoulder(lin)
    lin = np.clip(lin, 0.0, 1.0)
    enc = bt1886_encode(lin)
    with open(out, "w") as f:
        f.write("TITLE \"S-Log3 S-Gamut3 to Rec709 (Balgio)\"\n")
        f.write(f"LUT_3D_SIZE {N}\n")
        f.write("DOMAIN_MIN 0.0 0.0 0.0\nDOMAIN_MAX 1.0 1.0 1.0\n")
        for row in enc:
            f.write(f"{row[0]:.6f} {row[1]:.6f} {row[2]:.6f}\n")
    print(f"LUT écrite : {out} ({N}^3)")

if __name__ == "__main__":
    main(sys.argv[1])
