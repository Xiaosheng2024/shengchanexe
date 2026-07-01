import unittest

from shared.s7_plc_client import S7PlcClient


class MutatingSnap7Util:
    received_types = []

    @classmethod
    def remember(cls, data):
        cls.received_types.append(type(data))
        data[0] = data[0]

    @classmethod
    def get_int(cls, data, offset):
        cls.remember(data)
        return int.from_bytes(data[offset:offset + 2], "big", signed=True)

    @classmethod
    def get_dint(cls, data, offset):
        cls.remember(data)
        return int.from_bytes(data[offset:offset + 4], "big", signed=True)

    @classmethod
    def get_real(cls, data, offset):
        cls.remember(data)
        return 1.5

    @classmethod
    def get_bool(cls, data, byte_index, bit_index):
        cls.remember(data)
        return bool(data[byte_index] & (1 << bit_index))


class S7PlcClientParsingTest(unittest.TestCase):
    def make_client(self, raw):
        client = S7PlcClient("127.0.0.1")
        client.snap7_util = MutatingSnap7Util
        client.read_bytes = lambda db_number, offset, length: bytes(raw[:length])
        return client

    def setUp(self):
        MutatingSnap7Util.received_types = []

    def test_read_int_converts_bytes_to_mutable_bytearray(self):
        client = self.make_client(b"\x00\x2a")

        self.assertEqual(client.read_int(221, 358), 42)
        self.assertEqual(MutatingSnap7Util.received_types, [bytearray])

    def test_other_snap7_parsers_also_receive_bytearray(self):
        number_client = self.make_client(b"\x00\x00\x00\x08")
        bool_client = self.make_client(b"\x08")

        self.assertEqual(number_client.read_dint(1, 0), 8)
        self.assertEqual(number_client.read_real(1, 0), 1.5)
        self.assertTrue(bool_client.read_bool(1, 0, 3))
        self.assertEqual(
            MutatingSnap7Util.received_types,
            [bytearray, bytearray, bytearray],
        )

    def test_read_bool_rejects_invalid_bit_index(self):
        client = self.make_client(b"\x01")

        with self.assertRaisesRegex(ValueError, "0-7"):
            client.read_bool(1, 0, 8)


if __name__ == "__main__":
    unittest.main()
