#!/usr/bin/env python3

import unittest
import hashlib
from mdsh5 import read_mds
import platform

if platform.system() == 'Linux':
    D3D_sha256 = 'f9409614c7d98f6c3fceec81b3d29e836fd6355a7da600a5eb39cdae7feace02'
    KSTAR_sha256 = '10ae3a0721288e9b6494e92ee848e0571bf7c76190d92a7e9676b4aa00ed2a98'
elif platform.system() == 'Darwin':
    D3D_sha256 = 'd18a8c91bda2ded5155503b12cc190b47515bed40c98b229f7d0fb6f56dcccd7'
    KSTAR_sha256 = '14d563ac396df2ebafb7fd59312bd5ca0ab20d92eebefaa6edc05ad81c31bbc0'


class TestDataDownload(unittest.TestCase):
    """tests data downloading."""

    def test_d3d(self):
        read_mds(config='mdsh5/config_examples/d3d.yml', out_filename='D3D.h5')
        sha256 = self.calculate_sha256('D3D.h5')
        self.assertEqual(sha256, D3D_sha256,
                         "SHA256 checksums do not match for D3D.")

    def test_kstar(self):
        read_mds(config='mdsh5/config_examples/kstar.yml',
                 out_filename='KSTAR.h5')
        sha256 = self.calculate_sha256('KSTAR.h5')
        self.assertEqual(sha256, KSTAR_sha256,
                         "SHA256 checksums do not match for KSTAR.")

    def calculate_sha256(self, filename):
        sha256_hash = hashlib.sha256()
        with open(filename, "rb") as f:
            for byte_block in iter(lambda: f.read(4096), b""):
                sha256_hash.update(byte_block)
        return sha256_hash.hexdigest()


if __name__ == '__main__':
    unittest.main()
