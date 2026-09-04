"""Tests du conteneur .prn.

Les cas « échantillons de production » rejouent les 5 fichiers réels documentés
au §7 du dossier de rétro-ingénierie. Ils ne vérifient pas notre code contre
lui-même : ils vérifient qu'il reproduit une géométrie observée sur des fichiers
qui ont réellement imprimé.
"""

from __future__ import annotations

import struct

import numpy as np
import pytest

from ripcore.errors import PrnFormatError
from ripcore.prnfile import (
    HEADER_SIZE,
    MARKER,
    PrnHeader,
    PrnReader,
    PrnWriter,
    bytes_per_line,
    pack_levels,
    probe,
    unpack_levels,
    write_prn,
)

# (nom, dpi_x, dpi_y, octets/ligne/canal, lignes, canaux, pass_mode)
PRODUCTION_SAMPLES = [
    ("111.prn", 720, 900, 1024, 6358, 5, 0),
    ("12.prn", 720, 1200, 1024, 8477, 5, 4),
    ("22.prn", 720, 1200, 852, 5669, 5, 4),
    ("22222.prn", 720, 900, 2128, 10632, 5, 0),
    ("666.prn", 720, 900, 1420, 7088, 5, 0),
]

# Carrés attendus, calculés depuis la géométrie et recoupés dans docs/prn-format.md
SQUARE_SAMPLES = {"22.prn": 120.0, "666.prn": 200.0, "22222.prn": 300.0}


def sample_header(row) -> PrnHeader:
    _, dpi_x, dpi_y, bpl, lines, channels, pass_mode = row
    return PrnHeader(
        dpi_x=dpi_x,
        dpi_y=dpi_y,
        bytes_per_line_per_channel=bpl,
        lines=lines,
        channels=channels,
        bits_per_pixel=2,
        pass_mode=pass_mode,
    )


class TestHeaderLayout:
    def test_taille_48_octets(self):
        hdr = sample_header(PRODUCTION_SAMPLES[0])
        assert len(hdr.pack()) == HEADER_SIZE

    def test_offsets_des_champs(self):
        """Chaque champ doit tomber à l'offset documenté."""
        hdr = PrnHeader(
            dpi_x=720,
            dpi_y=900,
            bytes_per_line_per_channel=1420,
            lines=7088,
            channels=5,
            bits_per_pixel=2,
            pass_mode=0,
        )
        b = hdr.pack()
        u32 = lambda off: struct.unpack_from("<I", b, off)[0]  # noqa: E731
        assert u32(0x00) == MARKER == 0x5555
        assert u32(0x04) == 720
        assert u32(0x08) == 900
        assert u32(0x0C) == 1420
        assert u32(0x10) == 7088
        assert u32(0x14) == 5670  # 7088 / 900 × 720
        assert struct.unpack_from("<f", b, 0x18)[0] == pytest.approx(0.2, abs=1e-4)
        assert u32(0x1C) == 5
        assert u32(0x20) == 2
        assert u32(0x24) == 0
        assert u32(0x28) == 0
        assert u32(0x2C) == 0

    def test_roundtrip(self):
        for row in PRODUCTION_SAMPLES:
            hdr = sample_header(row)
            assert PrnHeader.unpack(hdr.pack()) == hdr

    def test_dpi_nul_refuse(self):
        """Les deux seuls champs que le lecteur contrôle."""
        with pytest.raises(PrnFormatError, match="dpi_x"):
            PrnHeader(
                dpi_x=0, dpi_y=900, bytes_per_line_per_channel=8, lines=1,
                channels=1, bits_per_pixel=2, pass_mode=0,
            )
        with pytest.raises(PrnFormatError, match="dpi_y"):
            PrnHeader(
                dpi_x=720, dpi_y=0, bytes_per_line_per_channel=8, lines=1,
                channels=1, bits_per_pixel=2, pass_mode=0,
            )

    def test_champ_redondant_incoherent_detecte(self):
        hdr = sample_header(PRODUCTION_SAMPLES[4])
        b = bytearray(hdr.pack())
        struct.pack_into("<I", b, 0x14, 9999)  # height_720 faux
        with pytest.raises(PrnFormatError, match="0x14"):
            PrnHeader.unpack(bytes(b))


class TestProductionSamples:
    @pytest.mark.parametrize("row", PRODUCTION_SAMPLES, ids=lambda r: r[0])
    def test_invariant_de_taille(self, row):
        """taille − 48 == lignes × (o/ligne/canal × canaux), division exacte."""
        hdr = sample_header(row)
        assert hdr.body_size == hdr.lines * hdr.bytes_per_line_per_channel * hdr.channels
        assert hdr.body_size % hdr.lines == 0
        assert (hdr.body_size // hdr.lines) % hdr.channels == 0

    @pytest.mark.parametrize("row", PRODUCTION_SAMPLES, ids=lambda r: r[0])
    def test_hauteur_metrique(self, row):
        """0x18 == 0x14 / 720 × 0,0254, relation vérifiée sur les 5 fichiers."""
        hdr = sample_header(row)
        assert hdr.height_m == pytest.approx(hdr.height_720 / 720 * 0.0254, rel=1e-6)
        assert hdr.height_720 == pytest.approx(hdr.lines / hdr.dpi_y * 720, abs=1.0)

    @pytest.mark.parametrize("name,side", SQUARE_SAMPLES.items())
    def test_geometrie_carree(self, name, side):
        """Recoupement indépendant : ces trois jobs sont des carrés exacts."""
        row = next(r for r in PRODUCTION_SAMPLES if r[0] == name)
        hdr = sample_header(row)
        assert hdr.width_mm == pytest.approx(side, abs=0.5)
        assert hdr.height_mm == pytest.approx(side, abs=0.5)

    def test_largeur_derivee_des_octets_par_ligne(self):
        hdr = sample_header(PRODUCTION_SAMPLES[4])  # 666.prn
        assert hdr.width_px == 5680  # 1420 × 8 / 2
        assert bytes_per_line(5680, 2) == 1420


class TestPacking:
    @pytest.mark.parametrize("bpp", [1, 2, 4, 8])
    def test_roundtrip(self, bpp):
        rng = np.random.default_rng(1234)
        w = 1000
        levels = rng.integers(0, 1 << bpp, size=(5, 7, w), dtype=np.uint8)
        packed = pack_levels(levels, bpp)
        assert packed.shape[-1] == bytes_per_line(w, bpp)
        assert np.array_equal(unpack_levels(packed, bpp, w), levels)

    def test_msb_dabord_2bpp(self):
        """Pixel 0 dans les bits 7-6 — masques {0xFF,0x3F,0x0F,0x03} de ipht.dll."""
        levels = np.array([[3, 2, 1, 0]], dtype=np.uint8)
        assert pack_levels(levels, 2).tolist() == [[0b11_10_01_00]]

    def test_msb_dabord_1bpp(self):
        levels = np.array([[1, 0, 0, 0, 0, 0, 0, 1]], dtype=np.uint8)
        assert pack_levels(levels, 1).tolist() == [[0b1000_0001]]

    def test_remplissage_a_zero(self):
        levels = np.full((1, 5), 3, dtype=np.uint8)  # 5 px → 2 octets, 3 px de padding
        assert pack_levels(levels, 2).tolist() == [[0xFF, 0b11_00_00_00]]

    def test_niveau_hors_domaine_refuse(self):
        with pytest.raises(PrnFormatError, match="hors domaine"):
            pack_levels(np.array([[4]], dtype=np.uint8), 2)


class TestWriter:
    def test_roundtrip_fichier(self, tmp_path):
        rng = np.random.default_rng(7)
        raster = rng.integers(0, 4, size=(5, 40, 133), dtype=np.uint8)
        path = tmp_path / "job.prn"
        hdr = write_prn(path, raster, dpi_x=720, dpi_y=900, bits_per_pixel=2, pass_mode=0)

        assert path.stat().st_size == hdr.file_size
        back = PrnReader(path, width_px=133).read_all()
        assert np.array_equal(back, raster)

    def test_ordre_planaire_par_canal(self, tmp_path):
        """Ligne = [canal0][canal1]… et non un entrelacement par pixel."""
        # canal c rempli de la valeur c+... : 4 px, 2 bpp → 1 octet par canal/ligne
        raster = np.zeros((3, 2, 4), dtype=np.uint8)
        raster[0] = 1  # 0b01010101 = 0x55
        raster[1] = 2  # 0b10101010 = 0xAA
        raster[2] = 3  # 0b11111111 = 0xFF
        path = tmp_path / "planar.prn"
        write_prn(path, raster, dpi_x=720, dpi_y=900, bits_per_pixel=2, pass_mode=0)
        body = path.read_bytes()[HEADER_SIZE:]
        assert body == bytes([0x55, 0xAA, 0xFF, 0x55, 0xAA, 0xFF])

    def test_ecriture_en_bandes(self, tmp_path):
        rng = np.random.default_rng(11)
        raster = rng.integers(0, 4, size=(5, 100, 64), dtype=np.uint8)
        path = tmp_path / "bands.prn"
        with PrnWriter(
            path, dpi_x=720, dpi_y=1200, width_px=64, channels=5,
            bits_per_pixel=2, pass_mode=4,
        ) as w:
            for start in range(0, 100, 17):
                w.write_block(raster[:, start : start + 17])
        assert w.header.lines == 100
        assert np.array_equal(PrnReader(path).read_all(), raster)

    def test_atomicite_sur_erreur(self, tmp_path):
        path = tmp_path / "avorte.prn"
        with pytest.raises(PrnFormatError):
            with PrnWriter(
                path, dpi_x=720, dpi_y=900, width_px=64, channels=5,
                bits_per_pixel=2, pass_mode=0,
            ) as w:
                w.write_block(np.zeros((3, 4, 64), dtype=np.uint8))  # 3 ≠ 5 canaux
        assert not path.exists()
        assert not list(tmp_path.glob("*.part"))

    def test_prn_vide_refuse(self, tmp_path):
        path = tmp_path / "vide.prn"
        with pytest.raises(PrnFormatError, match="vide"):
            with PrnWriter(
                path, dpi_x=720, dpi_y=900, width_px=64, channels=5,
                bits_per_pixel=2, pass_mode=0,
            ):
                pass
        assert not path.exists()

    def test_statistiques(self, tmp_path):
        raster = np.zeros((2, 10, 8), dtype=np.uint8)
        raster[0] = 3  # canal 0 à fond
        path = tmp_path / "stats.prn"
        with PrnWriter(
            path, dpi_x=720, dpi_y=900, width_px=8, channels=2,
            bits_per_pixel=2, pass_mode=0,
        ) as w:
            w.write_block(raster)
        cov = w.stats.coverage((0.0, 1 / 3, 2 / 3, 1.0))
        assert cov[0] == pytest.approx(1.0)
        assert cov[1] == pytest.approx(0.0)


class TestReader:
    def test_dialectes_reconnus(self, tmp_path):
        for magic, name, size in [
            (b"ycdz", "ycdz", 64),
            (b"BYHX", "BYHX", 84),
            (b"ATCM", "ATCM", 84),
        ]:
            p = tmp_path / f"{name}.prn"
            p.write_bytes(magic + b"\x00" * 200)
            pr = probe(p)
            assert (pr.dialect, pr.header_size) == (name, size)
            assert not pr.supported

    def test_taille_incoherente_detectee(self, tmp_path):
        raster = np.zeros((5, 10, 64), dtype=np.uint8)
        path = tmp_path / "tronque.prn"
        write_prn(path, raster, dpi_x=720, dpi_y=900, bits_per_pixel=2, pass_mode=0)
        data = path.read_bytes()
        path.write_bytes(data[:-16])  # troncature
        with pytest.raises(PrnFormatError, match="taille"):
            PrnReader(path)
