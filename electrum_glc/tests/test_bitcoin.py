import base64
import sys

from electrum_glc.bitcoin import (public_key_to_p2pkh, address_from_private_key,
                                  is_address, is_private_key,
                                  var_int, _op_push, address_to_script, OnchainOutputType, address_to_payload,
                                  deserialize_privkey, serialize_privkey, is_segwit_address,
                                  is_b58_address, address_to_scripthash, is_minikey,
                                  is_compressed_privkey, EncodeBase58Check, DecodeBase58Check,
                                  script_num_to_hex, push_script, add_number_to_script, int_to_hex,
                                  opcodes, base_encode, base_decode, BitcoinException)
from electrum_glc import bip32
from electrum_glc import segwit_addr
from electrum_glc.segwit_addr import DecodedBech32
from electrum_glc.bip32 import (BIP32Node, convert_bip32_intpath_to_strpath,
                                xpub_from_xprv, xpub_type, is_xprv, is_bip32_derivation,
                                is_xpub, convert_bip32_path_to_list_of_uint32,
                                normalize_bip32_derivation, is_all_public_derivation)
from electrum_glc.crypto import sha256d, SUPPORTED_PW_HASH_VERSIONS
from electrum_glc import ecc, crypto, constants
from electrum_glc.util import bfh, bh2u, InvalidPassword, randrange
from electrum_glc.storage import WalletStorage
from electrum_glc.keystore import xtype_from_derivation

from electrum_glc import ecc_fast

from . import ElectrumTestCase
from . import TestCaseForTestnet
from . import FAST_TESTS


def needs_test_with_all_aes_implementations(func):
    """Function decorator to run a unit test multiple times:
    once with each AES implementation.

    NOTE: this is inherently sequential;
    tests running in parallel would break things
    """
    def run_test(*args, **kwargs):
        if FAST_TESTS:  # if set, only run tests once, using fastest implementation
            func(*args, **kwargs)
            return
        has_cryptodome = crypto.HAS_CRYPTODOME
        has_cryptography = crypto.HAS_CRYPTOGRAPHY
        has_pyaes = crypto.HAS_PYAES
        try:
            if has_pyaes:
                (crypto.HAS_CRYPTODOME, crypto.HAS_CRYPTOGRAPHY, crypto.HAS_PYAES) = False, False, True
                func(*args, **kwargs)  # pyaes
            if has_cryptodome:
                (crypto.HAS_CRYPTODOME, crypto.HAS_CRYPTOGRAPHY, crypto.HAS_PYAES) = True, False, False
                func(*args, **kwargs)  # cryptodome
            if has_cryptography:
                (crypto.HAS_CRYPTODOME, crypto.HAS_CRYPTOGRAPHY, crypto.HAS_PYAES) = False, True, False
                func(*args, **kwargs)  # cryptography
        finally:
            crypto.HAS_CRYPTODOME = has_cryptodome
            crypto.HAS_CRYPTOGRAPHY = has_cryptography
            crypto.HAS_PYAES = has_pyaes
    return run_test


def needs_test_with_all_chacha20_implementations(func):
    """Function decorator to run a unit test multiple times:
    once with each ChaCha20/Poly1305 implementation.

    NOTE: this is inherently sequential;
    tests running in parallel would break things
    """
    def run_test(*args, **kwargs):
        if FAST_TESTS:  # if set, only run tests once, using fastest implementation
            func(*args, **kwargs)
            return
        has_cryptodome = crypto.HAS_CRYPTODOME
        has_cryptography = crypto.HAS_CRYPTOGRAPHY
        try:
            if has_cryptodome:
                (crypto.HAS_CRYPTODOME, crypto.HAS_CRYPTOGRAPHY) = True, False
                func(*args, **kwargs)  # cryptodome
            if has_cryptography:
                (crypto.HAS_CRYPTODOME, crypto.HAS_CRYPTOGRAPHY) = False, True
                func(*args, **kwargs)  # cryptography
        finally:
            crypto.HAS_CRYPTODOME = has_cryptodome
            crypto.HAS_CRYPTOGRAPHY = has_cryptography
    return run_test


def disable_ecdsa_r_value_grinding(func):
    """Function decorator to run a unit test with ecdsa R-value grinding disabled.
    This is used when we want to pass test vectors that were created without R-value grinding.
    (see https://github.com/bitcoin/bitcoin/pull/13666 )

    NOTE: this is inherently sequential;
    tests running in parallel would break things
    """
    def run_test(*args, **kwargs):
        is_grinding = ecc.ENABLE_ECDSA_R_VALUE_GRINDING
        try:
            ecc.ENABLE_ECDSA_R_VALUE_GRINDING = False
            func(*args, **kwargs)
        finally:
            ecc.ENABLE_ECDSA_R_VALUE_GRINDING = is_grinding
    return run_test


class Test_bitcoin(ElectrumTestCase):

    def test_libsecp256k1_is_available(self):
        # we want the unit testing framework to test with libsecp256k1 available.
        self.assertTrue(bool(ecc_fast._libsecp256k1))

    def test_pycryptodomex_is_available(self):
        # we want the unit testing framework to test with pycryptodomex available.
        self.assertTrue(bool(crypto.HAS_CRYPTODOME))

    def test_cryptography_is_available(self):
        # we want the unit testing framework to test with cryptography available.
        self.assertTrue(bool(crypto.HAS_CRYPTOGRAPHY))

    def test_pyaes_is_available(self):
        # we want the unit testing framework to test with pyaes available.
        self.assertTrue(bool(crypto.HAS_PYAES))

    @needs_test_with_all_aes_implementations
    def test_crypto(self):
        for message in [b"Chancellor on brink of second bailout for banks", b'\xff'*512]:
            self._do_test_crypto(message)

    def _do_test_crypto(self, message):
        G = ecc.GENERATOR
        _r  = G.order()
        pvk = randrange(_r)

        Pub = pvk*G
        pubkey_c = Pub.get_public_key_bytes(True)
        #pubkey_u = point_to_ser(Pub,False)
        addr_c = public_key_to_p2pkh(pubkey_c)

        #print "Private key            ", '%064x'%pvk
        eck = ecc.ECPrivkey.from_secret_scalar(pvk)

        #print "Compressed public key  ", pubkey_c.encode('hex')
        enc = ecc.ECPubkey(pubkey_c).encrypt_message(message)
        dec = eck.decrypt_message(enc)
        self.assertEqual(message, dec)

        #print "Uncompressed public key", pubkey_u.encode('hex')
        #enc2 = EC_KEY.encrypt_message(message, pubkey_u)
        dec2 = eck.decrypt_message(enc)
        self.assertEqual(message, dec2)

        signature = eck.sign_message(message, True)
        #print signature
        self.assertTrue(eck.verify_message_for_address(signature, message))

    def test_ecc_sanity(self):
        G = ecc.GENERATOR
        n = G.order()
        self.assertEqual(ecc.CURVE_ORDER, n)
        inf = n * G
        self.assertEqual(ecc.POINT_AT_INFINITY, inf)
        self.assertTrue(inf.is_at_infinity())
        self.assertFalse(G.is_at_infinity())
        self.assertEqual(11 * G, 7 * G + 4 * G)
        self.assertEqual((n + 2) * G, 2 * G)
        self.assertEqual((n - 2) * G, -2 * G)
        A = (n - 2) * G
        B = (n - 1) * G
        C = n * G
        D = (n + 1) * G
        self.assertFalse(A.is_at_infinity())
        self.assertFalse(B.is_at_infinity())
        self.assertTrue(C.is_at_infinity())
        self.assertTrue((C * 5).is_at_infinity())
        self.assertFalse(D.is_at_infinity())
        self.assertEqual(inf, C)
        self.assertEqual(inf, A + 2 * G)
        self.assertEqual(inf, D + (-1) * G)
        self.assertNotEqual(A, B)
        self.assertEqual(2 * G, inf + 2 * G)
        self.assertEqual(inf, 3 * G + (-3 * G))

    @staticmethod
    def sign_message_with_wif_privkey(wif_privkey: str, msg: bytes) -> bytes:
        txin_type, privkey, compressed = deserialize_privkey(wif_privkey)
        key = ecc.ECPrivkey(privkey)
        return key.sign_message(msg, compressed)

    def test_signmessage_legacy_address(self):
        msg1 = b'Chancellor on brink of second bailout for banks'
        msg2 = b'Electrum'

        sig1 = self.sign_message_with_wif_privkey(
            'T7J3unHmmx9S8e8Zdi9r98A7wTW386HkxvMbUKEMsAY9JRWfbSe6', msg1)  # compressed pubkey
        addr1 = 'LPvBisC3rGmpGa3E3NeQk3PHQN4VS237y2'
        sig2 = self.sign_message_with_wif_privkey(
            '6uGWYKbyKLBMa1ysfq9rMANcbtYKY49vrawvaH3rBXooApLq6t2', msg2)  # uncompressed pubkey
        addr2 = 'LacEkfqxYsPqDuS8ZCstJUc59gxVm2DQaT'

        sig1_b64 = base64.b64encode(sig1)
        sig2_b64 = base64.b64encode(sig2)

        self.assertEqual(sig1_b64, b'IHGAMaPxjrn3CD19S7J5KAq4xF6mdLznsSL8SrqhNwficUHlK5wSth6/JiZ/pEyo92nkUoA+kL9VJpjLnKJKTmM=')
        self.assertEqual(sig2_b64, b'G14KtfFZQYjyhz4PUzX/yz8eEC1BFHsaEKZOJGLeTWJoNp/umpi5zPeCvhUcgSoMtAkmw3pATrM2bcDdYi1tqIs=')

        self.assertTrue(ecc.verify_message_with_address(addr1, sig1, msg1))
        self.assertTrue(ecc.verify_message_with_address(addr2, sig2, msg2))

        self.assertFalse(ecc.verify_message_with_address(addr1, b'wrong', msg1))
        self.assertFalse(ecc.verify_message_with_address(addr1, sig2, msg1))

    def test_signmessage_segwit_witness_v0_address(self):
        msg = b'Electrum'
        # p2wpkh-p2sh
        sig1 = self.sign_message_with_wif_privkey("p2wpkh-p2sh:T7Swnz5d7C5eczM5TPkFSPuBdCJDiTZK2MCkjU5ZZTU8u4z4cHWn", msg)
        addr1 = "MKkwVip3KDUb2WFJqr8bGebGPHNAXwGG1f"
        self.assertEqual(base64.b64encode(sig1), b'H3nh1AqVvauwclOAPs2serBtro9Iei1Q7vZZfmivo6ioQ6EzNYq5No90CU5RXM17d05eO+bXd0p/r/Sl5fPz390=')
        self.assertTrue(ecc.verify_message_with_address(addr1, sig1, msg))
        self.assertFalse(ecc.verify_message_with_address(addr1, sig1, b'heyheyhey'))
        # p2wpkh
        sig2 = self.sign_message_with_wif_privkey("p2wpkh:T7Swnz5d7C5eczM5TPkFSPuBdCJDiTZK2MCkjU5ZZTU8u4z4cHWn", msg)
        addr2 = "ltc1qq2tmmcngng78nllq2pvrkchcdukemtj57q7cpl"
        self.assertEqual(base64.b64encode(sig2), b'H3nh1AqVvauwclOAPs2serBtro9Iei1Q7vZZfmivo6ioQ6EzNYq5No90CU5RXM17d05eO+bXd0p/r/Sl5fPz390=')
        self.assertTrue(ecc.verify_message_with_address(addr2, sig2, msg))
        self.assertFalse(ecc.verify_message_with_address(addr2, sig2, b'heyheyhey'))

    def test_signmessage_segwit_witness_v0_address_test_we_also_accept_sigs_from_trezor(self):
        """Trezor and some other projects use a slightly different scheme for message-signing
        with p2wpkh and p2wpkh-p2sh addresses. Test that we also accept signatures from them.
        see #3861
        tests from https://github.com/trezor/trezor-firmware/blob/2ce1e6ba7dbe5bbaeeb336fff0a038e59cb40ef8/tests/device_tests/bitcoin/test_signmessage.py#L39
        """
        msg = b"This is an example of a signed message."
        addr1 = "MS2NsKymog9TrEVq4wbrjn1oYS7MiPDkqR"
        addr2 = "ltc1qnw6a545d64e94r4vts80n89nmcpud5fdftvryq"
        sig1 = bytes.fromhex("23744de4516fac5c140808015664516a32fead94de89775cec7e24dbc24fe133075ac09301c4cc8e197bea4b6481661d5b8e9bf19d8b7b8a382ecdb53c2ee0750d")
        sig2 = bytes.fromhex("28b55d7600d9e9a7e2a49155ddf3cfdb8e796c207faab833010fa41fb7828889bc47cf62348a7aaa0923c0832a589fab541e8f12eb54fb711c90e2307f0f66b194")
        self.assertTrue(ecc.verify_message_with_address(address=addr1, sig65=sig1, message=msg))
        self.assertTrue(ecc.verify_message_with_address(address=addr2, sig65=sig2, message=msg))
        # if there is type information in the header of the sig (first byte), enforce that:
        sig1_wrongtype = bytes.fromhex("27744de4516fac5c140808015664516a32fead94de89775cec7e24dbc24fe133075ac09301c4cc8e197bea4b6481661d5b8e9bf19d8b7b8a382ecdb53c2ee0750d")
        sig2_wrongtype = bytes.fromhex("24b55d7600d9e9a7e2a49155ddf3cfdb8e796c207faab833010fa41fb7828889bc47cf62348a7aaa0923c0832a589fab541e8f12eb54fb711c90e2307f0f66b194")
        self.assertFalse(ecc.verify_message_with_address(address=addr1, sig65=sig1_wrongtype, message=msg))
        self.assertFalse(ecc.verify_message_with_address(address=addr2, sig65=sig2_wrongtype, message=msg))

    @needs_test_with_all_aes_implementations
    def test_decrypt_message(self):
        key = WalletStorage.get_eckey_from_password('pw123')
        self.assertEqual(b'me<(s_s)>age', key.decrypt_message(b'QklFMQMDFtgT3zWSQsa+Uie8H/WvfUjlu9UN9OJtTt3KlgKeSTi6SQfuhcg1uIz9hp3WIUOFGTLr4RNQBdjPNqzXwhkcPi2Xsbiw6UCNJncVPJ6QBg=='))
        self.assertEqual(b'me<(s_s)>age', key.decrypt_message(b'QklFMQKXOXbylOQTSMGfo4MFRwivAxeEEkewWQrpdYTzjPhqjHcGBJwdIhB7DyRfRQihuXx1y0ZLLv7XxLzrILzkl/H4YUtZB4uWjuOAcmxQH4i/Og=='))
        self.assertEqual(b'hey_there' * 100, key.decrypt_message(b'QklFMQLOOsabsXtGQH8edAa6VOUa5wX8/DXmxX9NyHoAx1a5bWgllayGRVPeI2bf0ZdWK0tfal0ap0ZIVKbd2eOJybqQkILqT6E1/Syzq0Zicyb/AA1eZNkcX5y4gzloxinw00ubCA8M7gcUjJpOqbnksATcJ5y2YYXcHMGGfGurWu6uJ/UyrNobRidWppRMW5yR9/6utyNvT6OHIolCMEf7qLcmtneoXEiz51hkRdZS7weNf9mGqSbz9a2NL3sdh1A0feHIjAZgcCKcAvksNUSauf0/FnIjzTyPRpjRDMeDC8Ci3sGiuO3cvpWJwhZfbjcS26KmBv2CHWXfRRNFYOInHZNIXWNAoBB47Il5bGSMd+uXiGr+SQ9tNvcu+BiJNmFbxYqg+oQ8dGAl1DtvY2wJVY8k7vO9BIWSpyIxfGw7EDifhc5vnOmGe016p6a01C3eVGxgl23UYMrP7+fpjOcPmTSF4rk5U5ljEN3MSYqlf1QEv0OqlI9q1TwTK02VBCjMTYxDHsnt04OjNBkNO8v5uJ4NR+UUDBEp433z53I59uawZ+dbk4v4ZExcl8EGmKm3Gzbal/iJ/F7KQuX2b/ySEhLOFVYFWxK73X1nBvCSK2mC2/8fCw8oI5pmvzJwQhcCKTdEIrz3MMvAHqtPScDUOjzhXxInQOCb3+UBj1PPIdqkYLvZss1TEaBwYZjLkVnK2MBj7BaqT6Rp6+5A/fippUKHsnB6eYMEPR2YgDmCHL+4twxHJG6UWdP3ybaKiiAPy2OHNP6PTZ0HrqHOSJzBSDD+Z8YpaRg29QX3UEWlqnSKaan0VYAsV1VeaN0XFX46/TWO0L5tjhYVXJJYGqo6tIQJymxATLFRF6AZaD1Mwd27IAL04WkmoQoXfO6OFfwdp/shudY/1gBkDBvGPICBPtnqkvhGF+ZF3IRkuPwiFWeXmwBxKHsRx/3+aJu32Ml9+za41zVk2viaxcGqwTc5KMexQFLAUwqhv+aIik7U+5qk/gEVSuRoVkihoweFzKolNF+BknH2oB4rZdPixag5Zje3DvgjsSFlOl69W/67t/Gs8htfSAaHlsB8vWRQr9+v/lxTbrAw+O0E+sYGoObQ4qQMyQshNZEHbpPg63eWiHtJJnrVBvOeIbIHzoLDnMDsWVWZSMzAQ1vhX1H5QLgSEbRlKSliVY03kDkh/Nk/KOn+B2q37Ialq4JcRoIYFGJ8AoYEAD0tRuTqFddIclE75HzwaNG7NyKW1plsa72ciOPwsPJsdd5F0qdSQ3OSKtooTn7uf6dXOc4lDkfrVYRlZ0PX'))

    @needs_test_with_all_aes_implementations
    def test_encrypt_message(self):
        key = WalletStorage.get_eckey_from_password('secret_password77')
        msgs = [
            bytes([0] * 555),
            b'cannot think of anything funny'
        ]
        for plaintext in msgs:
            ciphertext1 = key.encrypt_message(plaintext)
            ciphertext2 = key.encrypt_message(plaintext)
            self.assertEqual(plaintext, key.decrypt_message(ciphertext1))
            self.assertEqual(plaintext, key.decrypt_message(ciphertext2))
            self.assertNotEqual(ciphertext1, ciphertext2)

    def test_sign_transaction(self):
        eckey1 = ecc.ECPrivkey(bfh('7e1255fddb52db1729fc3ceb21a46f95b8d9fe94cc83425e936a6c5223bb679d'))
        sig1 = eckey1.sign_transaction(bfh('5a548b12369a53faaa7e51b5081829474ebdd9c924b3a8230b69aa0be254cd94'))
        self.assertEqual('3044022066e7d6a954006cce78a223f5edece8aaedcf3607142e9677acef1cfcb91cfdde022065cb0b5401bf16959ce7b785ea7fd408be5e4cb7d8f1b1a32c78eac6f73678d9', sig1.hex())

        eckey2 = ecc.ECPrivkey(bfh('c7ce8c1462c311eec24dff9e2532ac6241e50ae57e7d1833af21942136972f23'))
        sig2 = eckey2.sign_transaction(bfh('642a2e66332f507c92bda910158dfe46fc10afbf72218764899d3af99a043fac'))
        self.assertEqual('30440220618513f4cfc87dde798ce5febae7634c23e7b9254a1eabf486be820f6a7c2c4702204fef459393a2b931f949e63ced06888f35e286e446dc46feb24b5b5f81c6ed52', sig2.hex())

    @disable_ecdsa_r_value_grinding
    def test_sign_transaction_without_ecdsa_r_value_grinding(self):
        eckey1 = ecc.ECPrivkey(bfh('7e1255fddb52db1729fc3ceb21a46f95b8d9fe94cc83425e936a6c5223bb679d'))
        sig1 = eckey1.sign_transaction(bfh('5a548b12369a53faaa7e51b5081829474ebdd9c924b3a8230b69aa0be254cd94'))
        self.assertEqual('3045022100902a288b98392254cd23c0e9a49ac6d7920f171b8249a48e484b998f1874a2010220723d844826828f092cf400cb210c4fa0b8cd1b9d1a7f21590e78e022ff6476b9', sig1.hex())

    @needs_test_with_all_aes_implementations
    def test_aes_homomorphic(self):
        """Make sure AES is homomorphic."""
        payload = u'\u66f4\u7a33\u5b9a\u7684\u4ea4\u6613\u5e73\u53f0'
        password = u'secret'
        for version in SUPPORTED_PW_HASH_VERSIONS:
            enc = crypto.pw_encode(payload, password, version=version)
            dec = crypto.pw_decode(enc, password, version=version)
            self.assertEqual(dec, payload)

    @needs_test_with_all_aes_implementations
    def test_aes_encode_without_password(self):
        """When not passed a password, pw_encode is noop on the payload."""
        payload = u'\u66f4\u7a33\u5b9a\u7684\u4ea4\u6613\u5e73\u53f0'
        for version in SUPPORTED_PW_HASH_VERSIONS:
            enc = crypto.pw_encode(payload, None, version=version)
            self.assertEqual(payload, enc)

    @needs_test_with_all_aes_implementations
    def test_aes_deencode_without_password(self):
        """When not passed a password, pw_decode is noop on the payload."""
        payload = u'\u66f4\u7a33\u5b9a\u7684\u4ea4\u6613\u5e73\u53f0'
        for version in SUPPORTED_PW_HASH_VERSIONS:
            enc = crypto.pw_decode(payload, None, version=version)
            self.assertEqual(payload, enc)

    @needs_test_with_all_aes_implementations
    def test_aes_decode_with_invalid_password(self):
        """pw_decode raises an Exception when supplied an invalid password."""
        payload = u"blah"
        password = u"uber secret"
        wrong_password = u"not the password"
        for version in SUPPORTED_PW_HASH_VERSIONS:
            enc = crypto.pw_encode(payload, password, version=version)
            with self.assertRaises(InvalidPassword):
                crypto.pw_decode(enc, wrong_password, version=version)
        # sometimes the PKCS7 padding gets removed cleanly,
        # but then UnicodeDecodeError gets raised (internally):
        enc = 'smJ7j6ccr8LnMOlx98s/ajgikv9s3R1PQuG3GyyIMmo='
        with self.assertRaises(InvalidPassword):
            crypto.pw_decode(enc, wrong_password, version=1)

    @needs_test_with_all_chacha20_implementations
    def test_chacha20_poly1305_encrypt__with_associated_data(self):
        key = bytes.fromhex('37326d9d69a83b815ddfd947d21b0dd39111e5b6a5a44042c44d570ea03e3179')
        nonce = bytes.fromhex('010203040506070809101112')
        associated_data = bytes.fromhex('30c9572d4305d4f3ccb766b1db884da6f1e0086f55136a39740700c272095717')
        data = bytes.fromhex('4a6cd75da76cedf0a8a47e3a5734a328')
        self.assertEqual(bytes.fromhex('90fb51fcde1fbe4013500bd7a32280445d80ee21f0aa3acd30df72cf609de064'),
                         crypto.chacha20_poly1305_encrypt(key=key, nonce=nonce, associated_data=associated_data, data=data))

    @needs_test_with_all_chacha20_implementations
    def test_chacha20_poly1305_decrypt__with_associated_data(self):
        key = bytes.fromhex('37326d9d69a83b815ddfd947d21b0dd39111e5b6a5a44042c44d570ea03e3179')
        nonce = bytes.fromhex('010203040506070809101112')
        associated_data = bytes.fromhex('30c9572d4305d4f3ccb766b1db884da6f1e0086f55136a39740700c272095717')
        data = bytes.fromhex('90fb51fcde1fbe4013500bd7a32280445d80ee21f0aa3acd30df72cf609de064')
        self.assertEqual(bytes.fromhex('4a6cd75da76cedf0a8a47e3a5734a328'),
                         crypto.chacha20_poly1305_decrypt(key=key, nonce=nonce, associated_data=associated_data, data=data))
        with self.assertRaises(ValueError):
            crypto.chacha20_poly1305_decrypt(key=key, nonce=nonce, associated_data=b'', data=data)

    @needs_test_with_all_chacha20_implementations
    def test_chacha20_poly1305_encrypt__without_associated_data(self):
        key = bytes.fromhex('37326d9d69a83b815ddfd947d21b0dd39111e5b6a5a44042c44d570ea03e3179')
        nonce = bytes.fromhex('010203040506070809101112')
        data = bytes.fromhex('4a6cd75da76cedf0a8a47e3a5734a328')
        self.assertEqual(bytes.fromhex('90fb51fcde1fbe4013500bd7a322804469c2be9b1385bc5ded5cd96be510280f'),
                         crypto.chacha20_poly1305_encrypt(key=key, nonce=nonce, data=data))
        self.assertEqual(bytes.fromhex('90fb51fcde1fbe4013500bd7a322804469c2be9b1385bc5ded5cd96be510280f'),
                         crypto.chacha20_poly1305_encrypt(key=key, nonce=nonce, data=data, associated_data=b''))

    @needs_test_with_all_chacha20_implementations
    def test_chacha20_poly1305_decrypt__without_associated_data(self):
        key = bytes.fromhex('37326d9d69a83b815ddfd947d21b0dd39111e5b6a5a44042c44d570ea03e3179')
        nonce = bytes.fromhex('010203040506070809101112')
        data = bytes.fromhex('90fb51fcde1fbe4013500bd7a322804469c2be9b1385bc5ded5cd96be510280f')
        self.assertEqual(bytes.fromhex('4a6cd75da76cedf0a8a47e3a5734a328'),
                         crypto.chacha20_poly1305_decrypt(key=key, nonce=nonce, data=data))
        self.assertEqual(bytes.fromhex('4a6cd75da76cedf0a8a47e3a5734a328'),
                         crypto.chacha20_poly1305_decrypt(key=key, nonce=nonce, data=data, associated_data=b''))

    @needs_test_with_all_chacha20_implementations
    def test_chacha20_encrypt__8_byte_nonce(self):
        key = bytes.fromhex('37326d9d69a83b815ddfd947d21b0dd39111e5b6a5a44042c44d570ea03e3179')
        nonce = bytes.fromhex('0102030405060708')
        data = bytes.fromhex('38a0e0a7c865fe9ca31f0730cfcab610f18e6da88dc3790f1d243f711a257c78')
        ciphertext = crypto.chacha20_encrypt(key=key, nonce=nonce, data=data)
        self.assertEqual(bytes.fromhex('f62fbd74d197323c7c3d5658476a884d38ee6f4b5500add1e8dc80dcd9c15dff'), ciphertext)
        self.assertEqual(data, crypto.chacha20_decrypt(key=key, nonce=nonce, data=ciphertext))

    @needs_test_with_all_chacha20_implementations
    def test_chacha20_encrypt__12_byte_nonce(self):
        key = bytes.fromhex('37326d9d69a83b815ddfd947d21b0dd39111e5b6a5a44042c44d570ea03e3179')
        nonce = bytes.fromhex('010203040506070809101112')
        data = bytes.fromhex('38a0e0a7c865fe9ca31f0730cfcab610f18e6da88dc3790f1d243f711a257c78')
        ciphertext = crypto.chacha20_encrypt(key=key, nonce=nonce, data=data)
        self.assertEqual(bytes.fromhex('c0b1cb75c3c23c13f47dab393add738c92c62c4e2546cb3bf2b48269a4184028'), ciphertext)
        self.assertEqual(data, crypto.chacha20_decrypt(key=key, nonce=nonce, data=ciphertext))

    def test_sha256d(self):
        self.assertEqual(b'\x95MZI\xfdp\xd9\xb8\xbc\xdb5\xd2R&x)\x95\x7f~\xf7\xfalt\xf8\x84\x19\xbd\xc5\xe8"\t\xf4',
                         sha256d(u"test"))

    def test_int_to_hex(self):
        self.assertEqual('00', int_to_hex(0, 1))
        self.assertEqual('ff', int_to_hex(-1, 1))
        self.assertEqual('00000000', int_to_hex(0, 4))
        self.assertEqual('01000000', int_to_hex(1, 4))
        self.assertEqual('7f', int_to_hex(127, 1))
        self.assertEqual('7f00', int_to_hex(127, 2))
        self.assertEqual('80', int_to_hex(128, 1))
        self.assertEqual('80', int_to_hex(-128, 1))
        self.assertEqual('8000', int_to_hex(128, 2))
        self.assertEqual('ff', int_to_hex(255, 1))
        self.assertEqual('ff7f', int_to_hex(32767, 2))
        self.assertEqual('0080', int_to_hex(-32768, 2))
        self.assertEqual('ffff', int_to_hex(65535, 2))
        with self.assertRaises(OverflowError): int_to_hex(256, 1)
        with self.assertRaises(OverflowError): int_to_hex(-129, 1)
        with self.assertRaises(OverflowError): int_to_hex(-257, 1)
        with self.assertRaises(OverflowError): int_to_hex(65536, 2)
        with self.assertRaises(OverflowError): int_to_hex(-32769, 2)

    def test_var_int(self):
        for i in range(0xfd):
            self.assertEqual(var_int(i), "{:02x}".format(i))

        self.assertEqual(var_int(0xfd), "fdfd00")
        self.assertEqual(var_int(0xfe), "fdfe00")
        self.assertEqual(var_int(0xff), "fdff00")
        self.assertEqual(var_int(0x1234), "fd3412")
        self.assertEqual(var_int(0xffff), "fdffff")
        self.assertEqual(var_int(0x10000), "fe00000100")
        self.assertEqual(var_int(0x12345678), "fe78563412")
        self.assertEqual(var_int(0xffffffff), "feffffffff")
        self.assertEqual(var_int(0x100000000), "ff0000000001000000")
        self.assertEqual(var_int(0x0123456789abcdef), "ffefcdab8967452301")

    def test_op_push(self):
        self.assertEqual(_op_push(0x00), '00')
        self.assertEqual(_op_push(0x12), '12')
        self.assertEqual(_op_push(0x4b), '4b')
        self.assertEqual(_op_push(0x4c), '4c4c')
        self.assertEqual(_op_push(0xfe), '4cfe')
        self.assertEqual(_op_push(0xff), '4cff')
        self.assertEqual(_op_push(0x100), '4d0001')
        self.assertEqual(_op_push(0x1234), '4d3412')
        self.assertEqual(_op_push(0xfffe), '4dfeff')
        self.assertEqual(_op_push(0xffff), '4dffff')
        self.assertEqual(_op_push(0x10000), '4e00000100')
        self.assertEqual(_op_push(0x12345678), '4e78563412')

    def test_script_num_to_hex(self):
        # test vectors from https://github.com/btcsuite/btcd/blob/fdc2bc867bda6b351191b5872d2da8270df00d13/txscript/scriptnum.go#L77
        self.assertEqual(script_num_to_hex(127), '7f')
        self.assertEqual(script_num_to_hex(-127), 'ff')
        self.assertEqual(script_num_to_hex(128), '8000')
        self.assertEqual(script_num_to_hex(-128), '8080')
        self.assertEqual(script_num_to_hex(129), '8100')
        self.assertEqual(script_num_to_hex(-129), '8180')
        self.assertEqual(script_num_to_hex(256), '0001')
        self.assertEqual(script_num_to_hex(-256), '0081')
        self.assertEqual(script_num_to_hex(32767), 'ff7f')
        self.assertEqual(script_num_to_hex(-32767), 'ffff')
        self.assertEqual(script_num_to_hex(32768), '008000')
        self.assertEqual(script_num_to_hex(-32768), '008080')

    def test_push_script(self):
        # https://github.com/bitcoin/bips/blob/master/bip-0062.mediawiki#push-operators
        self.assertEqual(push_script(''), bh2u(bytes([opcodes.OP_0])))
        self.assertEqual(push_script('07'), bh2u(bytes([opcodes.OP_7])))
        self.assertEqual(push_script('10'), bh2u(bytes([opcodes.OP_16])))
        self.assertEqual(push_script('81'), bh2u(bytes([opcodes.OP_1NEGATE])))
        self.assertEqual(push_script('11'), '0111')
        self.assertEqual(push_script(75 * '42'), '4b' + 75 * '42')
        self.assertEqual(push_script(76 * '42'), bh2u(bytes([opcodes.OP_PUSHDATA1]) + bfh('4c' + 76 * '42')))
        self.assertEqual(push_script(100 * '42'), bh2u(bytes([opcodes.OP_PUSHDATA1]) + bfh('64' + 100 * '42')))
        self.assertEqual(push_script(255 * '42'), bh2u(bytes([opcodes.OP_PUSHDATA1]) + bfh('ff' + 255 * '42')))
        self.assertEqual(push_script(256 * '42'), bh2u(bytes([opcodes.OP_PUSHDATA2]) + bfh('0001' + 256 * '42')))
        self.assertEqual(push_script(520 * '42'), bh2u(bytes([opcodes.OP_PUSHDATA2]) + bfh('0802' + 520 * '42')))

    def test_add_number_to_script(self):
        # https://github.com/bitcoin/bips/blob/master/bip-0062.mediawiki#numbers
        self.assertEqual(add_number_to_script(0), bytes([opcodes.OP_0]))
        self.assertEqual(add_number_to_script(7), bytes([opcodes.OP_7]))
        self.assertEqual(add_number_to_script(16), bytes([opcodes.OP_16]))
        self.assertEqual(add_number_to_script(-1), bytes([opcodes.OP_1NEGATE]))
        self.assertEqual(add_number_to_script(-127), bfh('01ff'))
        self.assertEqual(add_number_to_script(-2), bfh('0182'))
        self.assertEqual(add_number_to_script(17), bfh('0111'))
        self.assertEqual(add_number_to_script(127), bfh('017f'))
        self.assertEqual(add_number_to_script(-32767), bfh('02ffff'))
        self.assertEqual(add_number_to_script(-128), bfh('028080'))
        self.assertEqual(add_number_to_script(128), bfh('028000'))
        self.assertEqual(add_number_to_script(32767), bfh('02ff7f'))
        self.assertEqual(add_number_to_script(-8388607), bfh('03ffffff'))
        self.assertEqual(add_number_to_script(-32768), bfh('03008080'))
        self.assertEqual(add_number_to_script(32768), bfh('03008000'))
        self.assertEqual(add_number_to_script(8388607), bfh('03ffff7f'))
        self.assertEqual(add_number_to_script(-2147483647), bfh('04ffffffff'))
        self.assertEqual(add_number_to_script(-8388608), bfh('0400008080'))
        self.assertEqual(add_number_to_script(8388608), bfh('0400008000'))
        self.assertEqual(add_number_to_script(2147483647), bfh('04ffffff7f'))

    def test_address_to_script(self):
        # bech32/bech32m native segwit
        # test vectors from BIP-0173
        # note: the ones that are commented out have been invalidated by BIP-0350
        self.assertEqual(address_to_script('LTC1QW508D6QEJXTDG4Y5R3ZARVARY0C5XW7KGMN4N9'), '0014751e76e8199196d454941c45d1b3a323f1433bd6')
        # self.assertEqual(address_to_script('ltc1pw508d6qejxtdg4y5r3zarvary0c5xw7kw508d6qejxtdg4y5r3zarvary0c5xw7k0tul4w'), '5128751e76e8199196d454941c45d1b3a323f1433bd6751e76e8199196d454941c45d1b3a323f1433bd6')
        # self.assertEqual(address_to_script('LTC1SW50QZGYDF5'), '6002751e')
        # self.assertEqual(address_to_script('ltc1zw508d6qejxtdg4y5r3zarvaryvdzur3w'), '5210751e76e8199196d454941c45d1b3a323')

        # bech32/bech32m native segwit
        # test vectors from BIP-0350
        self.assertEqual(address_to_script('ltc1pw508d6qejxtdg4y5r3zarvary0c5xw7kw508d6qejxtdg4y5r3zarvary0c5xw7k6hvnsv'), '5128751e76e8199196d454941c45d1b3a323f1433bd6751e76e8199196d454941c45d1b3a323f1433bd6')
        self.assertEqual(address_to_script('LTC1SW50QH55PVK'), '6002751e')
        self.assertEqual(address_to_script('ltc1zw508d6qejxtdg4y5r3zarvaryvc7v05v'), '5210751e76e8199196d454941c45d1b3a323')
        self.assertEqual(address_to_script('ltc1p0xlxvlhemja6c4dqv22uapctqupfhlxm9h8z3k2e72q4k9hcz7vqpj6zg2'), '512079be667ef9dcbbac55a06295ce870b07029bfcdb2dce28d959f2815b16f81798')

        # invalid addresses (from BIP-0173)
        self.assertFalse(is_address('tc1qw508d6qejxtdg4y5r3zarvary0c5xw7kg3g4ty'))
        self.assertFalse(is_address('bc1qw508d6qejxtdg4y5r3zarvary0c5xw7kv8f3t5'))
        self.assertFalse(is_address('LTC13W508D6QEJXTDG4Y5R3ZARVARY0C5XW7KHF4236'))
        self.assertFalse(is_address('ltc1rw58r3kry'))
        self.assertFalse(is_address('ltc10w508d6qejxtdg4y5r3zarvary0c5xw7kw508d6qejxtdg4y5r3zarvary0c5xw7kw5m6y25d'))
        self.assertFalse(is_address('LTC1QR508D6QEJXTDG4Y5R3ZARVARYVQLZUFA'))
        self.assertFalse(is_address('tb1qrp33g0q5c5txsp9arysrx4k6zdkfs4nce4xj0gdcccefvpysxf3q0sL5k7'))
        self.assertFalse(is_address('ltc1zw508d6qejxtdg4y5r3zarvaryvqw53wr5'))
        self.assertFalse(is_address('tltc1qrp33g0q5c5txsp9arysrx4k6zdkfs4nce4xj0gdcccefvpysxf3pd9hq5n'))
        self.assertFalse(is_address('bc1gmk9yu'))

        # invalid addresses (from BIP-0350)
        self.assertFalse(is_address('tc1p0xlxvlhemja6c4dqv22uapctqupfhlxm9h8z3k2e72q4k9hcz7vq5zuyut'))
        self.assertFalse(is_address('ltc1p0xlxvlhemja6c4dqv22uapctqupfhlxm9h8z3k2e72q4k9hcz7vq5w2wdg'))
        self.assertFalse(is_address('tltc1z0xlxvlhemja6c4dqv22uapctqupfhlxm9h8z3k2e72q4k9hcz7vqhuhluk'))
        self.assertFalse(is_address('LTC1S0XLXVLHEMJA6C4DQV22UAPCTQUPFHLXM9H8Z3K2E72Q4K9HCZ7VQH3QF96'))
        self.assertFalse(is_address('ltc1qw508d6qejxtdg4y5r3zarvary0c5xw7ka8rek8'))
        self.assertFalse(is_address('tltc1q0xlxvlhemja6c4dqv22uapctqupfhlxm9h8z3k2e72q4k9hcz7vq4kwe2p'))
        self.assertFalse(is_address('bc1p38j9r5y49hruaue7wxjce0updqjuyyx0kh56v8s25huc6995vvpql3jow4'))
        self.assertFalse(is_address('LTC130XLXVLHEMJA6C4DQV22UAPCTQUPFHLXM9H8Z3K2E72Q4K9HCZ7VQAXQQAX'))
        self.assertFalse(is_address('ltc1pw5kmnaal'))
        self.assertFalse(is_address('ltc1p0xlxvlhemja6c4dqv22uapctqupfhlxm9h8z3k2e72q4k9hcz7v8n0nx0muaewav25f87rvw'))
        self.assertFalse(is_address('LTC1QR508D6QEJXTDG4Y5R3ZARVARYVQLZUFA'))
        self.assertFalse(is_address('tb1p0xlxvlhemja6c4dqv22uapctqupfhlxm9h8z3k2e72q4k9hcz7vq47Zagq'))
        self.assertFalse(is_address('ltc1p0xlxvlhemja6c4dqv22uapctqupfhlxm9h8z3k2e72q4k9hcz7v07q76tu3e'))
        self.assertFalse(is_address('tltc1p0xlxvlhemja6c4dqv22uapctqupfhlxm9h8z3k2e72q4k9hcz7vpht2f2d'))
        self.assertFalse(is_address('bc1gmk9yu'))

        # base58 P2PKH
        self.assertEqual(address_to_script('LNuZh2Eeps3L114Lu4PVCxBR61UvrUKgze'), '76a91428662c67561b95c79d2257d2a93d9d151c977e9188ac')
        self.assertEqual(address_to_script('LVTnwCztciF3bcZpSqvJStuMSXrnCcRjNm'), '76a914704f4b81cadb7bf7e68c08cd3657220f680f863c88ac')

        # base58 P2SH
        self.assertEqual(address_to_script('MBmyiC29MUQSfPC2gKtdrazbSWHvGqJCnU'), 'a9142a84cf00d47f699ee7bbc1dea5ec1bdecb4ac15487')
        self.assertEqual(address_to_script('MWBtJBTgiEWYQ7m17wFktku2dvSFZXqhWZ'), 'a914f47c8954e421031ad04ecd8e7752c9479206b9d387')

    def test_address_to_payload(self):
        # bech32 P2WPKH
        self.assertEqual(
            address_to_payload('ltc1qw508d6qejxtdg4y5r3zarvary0c5xw7kgmn4n9'),
            (OnchainOutputType.WITVER0_P2WPKH, bytes.fromhex('751e76e8199196d454941c45d1b3a323f1433bd6')))

        # bech32 P2WSH
        self.assertEqual(
            address_to_payload('ltc1qrp33g0q5c5txsp9arysrx4k6zdkfs4nce4xj0gdcccefvpysxf3qmu8tk5'),
            (OnchainOutputType.WITVER0_P2WSH, bytes.fromhex('1863143c14c5166804bd19203356da136c985678cd4d27a1b8c6329604903262')))

        # bech32m P2TR
        self.assertEqual(
            address_to_payload('ltc1p5cyxnuxmeuwuvkwfem96lqzszd02n6xdcjrs20cac6yqjjwudpxq4arnzx'),
            (OnchainOutputType.WITVER1_P2TR, bytes.fromhex('a60869f0dbcf1dc659c9cecbaf8050135ea9e8cdc487053f1dc6880949dc684c')))

        # base58 P2PKH
        self.assertEqual(
            address_to_payload('LNuZh2Eeps3L114Lu4PVCxBR61UvrUKgze'),
            (OnchainOutputType.P2PKH, bytes.fromhex('28662c67561b95c79d2257d2a93d9d151c977e91')))

        # base58 P2SH
        self.assertEqual(
            address_to_payload('MBmyiC29MUQSfPC2gKtdrazbSWHvGqJCnU'),
            (OnchainOutputType.P2SH, bytes.fromhex('2a84cf00d47f699ee7bbc1dea5ec1bdecb4ac154')))

    def test_bech32_decode(self):
        # bech32 native segwit
        # test vectors from BIP-0173
        self.assertEqual(DecodedBech32(segwit_addr.Encoding.BECH32, 'a', []),
                         segwit_addr.bech32_decode('A12UEL5L'))
        self.assertEqual(DecodedBech32(segwit_addr.Encoding.BECH32, 'a', []),
                         segwit_addr.bech32_decode('a12uel5l'))
        self.assertEqual(DecodedBech32(segwit_addr.Encoding.BECH32, 'an83characterlonghumanreadablepartthatcontainsthenumber1andtheexcludedcharactersbio', []),
                         segwit_addr.bech32_decode('an83characterlonghumanreadablepartthatcontainsthenumber1andtheexcludedcharactersbio1tt5tgs'))
        self.assertEqual(DecodedBech32(segwit_addr.Encoding.BECH32, 'abcdef', [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27, 28, 29, 30, 31]),
                         segwit_addr.bech32_decode('abcdef1qpzry9x8gf2tvdw0s3jn54khce6mua7lmqqqxw'))
        self.assertEqual(DecodedBech32(segwit_addr.Encoding.BECH32, '1', [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0]),
                         segwit_addr.bech32_decode('11qqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqc8247j'))
        self.assertEqual(DecodedBech32(segwit_addr.Encoding.BECH32, 'split', [24, 23, 25, 24, 22, 28, 1, 16, 11, 29, 8, 25, 23, 29, 19, 13, 16, 23, 29, 22, 25, 28, 1, 16, 11, 3, 25, 29, 27, 25, 3, 3, 29, 19, 11, 25, 3, 3, 25, 13, 24, 29, 1, 25, 3, 3, 25, 13]),
                         segwit_addr.bech32_decode('split1checkupstagehandshakeupstreamerranterredcaperred2y9e3w'))
        self.assertEqual(DecodedBech32(segwit_addr.Encoding.BECH32, '?', []),
                         segwit_addr.bech32_decode('?1ezyfcl'))

        self.assertEqual(DecodedBech32(None, None, None),
                         segwit_addr.bech32_decode('\x201nwldj5'))
        self.assertEqual(DecodedBech32(None, None, None),
                         segwit_addr.bech32_decode('\x7f1axkwrx'))
        self.assertEqual(DecodedBech32(None, None, None),
                         segwit_addr.bech32_decode('\x801eym55h'))
        self.assertEqual(DecodedBech32(None, None, None),
                         segwit_addr.bech32_decode('an84characterslonghumanreadablepartthatcontainsthenumber1andtheexcludedcharactersbio1569pvx'))
        self.assertEqual(DecodedBech32(None, None, None),
                         segwit_addr.bech32_decode('pzry9x0s0muk'))
        self.assertEqual(DecodedBech32(None, None, None),
                         segwit_addr.bech32_decode('1pzry9x0s0muk'))
        self.assertEqual(DecodedBech32(None, None, None),
                         segwit_addr.bech32_decode('x1b4n0q5v'))
        self.assertEqual(DecodedBech32(None, None, None),
                         segwit_addr.bech32_decode('li1dgmt3'))
        self.assertEqual(DecodedBech32(None, None, None),
                         segwit_addr.bech32_decode('de1lg7wt\xff'))
        self.assertEqual(DecodedBech32(None, None, None),
                         segwit_addr.bech32_decode('A1G7SGD8'))
        self.assertEqual(DecodedBech32(None, None, None),
                         segwit_addr.bech32_decode('10a06t8'))
        self.assertEqual(DecodedBech32(None, None, None),
                         segwit_addr.bech32_decode('1qzzfhee'))

        # test vectors from BIP-0350
        self.assertEqual(DecodedBech32(segwit_addr.Encoding.BECH32M, 'a', []),
                         segwit_addr.bech32_decode('A1LQFN3A'))
        self.assertEqual(DecodedBech32(segwit_addr.Encoding.BECH32M, 'a', []),
                         segwit_addr.bech32_decode('a1lqfn3a'))
        self.assertEqual(DecodedBech32(segwit_addr.Encoding.BECH32M, 'an83characterlonghumanreadablepartthatcontainsthetheexcludedcharactersbioandnumber1', []),
                         segwit_addr.bech32_decode('an83characterlonghumanreadablepartthatcontainsthetheexcludedcharactersbioandnumber11sg7hg6'))
        self.assertEqual(DecodedBech32(segwit_addr.Encoding.BECH32M, 'abcdef', [31, 30, 29, 28, 27, 26, 25, 24, 23, 22, 21, 20, 19, 18, 17, 16, 15, 14, 13, 12, 11, 10, 9, 8, 7, 6, 5, 4, 3, 2, 1, 0]),
                         segwit_addr.bech32_decode('abcdef1l7aum6echk45nj3s0wdvt2fg8x9yrzpqzd3ryx'))
        self.assertEqual(DecodedBech32(segwit_addr.Encoding.BECH32M, '1', [31, 31, 31, 31, 31, 31, 31, 31, 31, 31, 31, 31, 31, 31, 31, 31, 31, 31, 31, 31, 31, 31, 31, 31, 31, 31, 31, 31, 31, 31, 31, 31, 31, 31, 31, 31, 31, 31, 31, 31, 31, 31, 31, 31, 31, 31, 31, 31, 31, 31, 31, 31, 31, 31, 31, 31, 31, 31, 31, 31, 31, 31, 31, 31, 31, 31, 31, 31, 31, 31, 31, 31, 31, 31, 31, 31, 31, 31, 31, 31, 31, 31]),
                         segwit_addr.bech32_decode('11llllllllllllllllllllllllllllllllllllllllllllllllllllllllllllllllllllllllllllllllllludsr8'))
        self.assertEqual(DecodedBech32(segwit_addr.Encoding.BECH32M, 'split', [24, 23, 25, 24, 22, 28, 1, 16, 11, 29, 8, 25, 23, 29, 19, 13, 16, 23, 29, 22, 25, 28, 1, 16, 11, 3, 25, 29, 27, 25, 3, 3, 29, 19, 11, 25, 3, 3, 25, 13, 24, 29, 1, 25, 3, 3, 25, 13]),
                         segwit_addr.bech32_decode('split1checkupstagehandshakeupstreamerranterredcaperredlc445v'))
        self.assertEqual(DecodedBech32(segwit_addr.Encoding.BECH32M, '?', []),
                         segwit_addr.bech32_decode('?1v759aa'))

        self.assertEqual(DecodedBech32(None, None, None),
                         segwit_addr.bech32_decode('\x201xj0phk'))
        self.assertEqual(DecodedBech32(None, None, None),
                         segwit_addr.bech32_decode('\x7f1g6xzxy'))
        self.assertEqual(DecodedBech32(None, None, None),
                         segwit_addr.bech32_decode('\x801vctc34'))
        self.assertEqual(DecodedBech32(None, None, None),
                         segwit_addr.bech32_decode('an84characterslonghumanreadablepartthatcontainsthetheexcludedcharactersbioandnumber11d6pts4'))
        self.assertEqual(DecodedBech32(None, None, None),
                         segwit_addr.bech32_decode('qyrz8wqd2c9m'))
        self.assertEqual(DecodedBech32(None, None, None),
                         segwit_addr.bech32_decode('1qyrz8wqd2c9m'))
        self.assertEqual(DecodedBech32(None, None, None),
                         segwit_addr.bech32_decode('y1b0jsk6g'))
        self.assertEqual(DecodedBech32(None, None, None),
                         segwit_addr.bech32_decode('lt1igcx5c0'))
        self.assertEqual(DecodedBech32(None, None, None),
                         segwit_addr.bech32_decode('in1muywd'))
        self.assertEqual(DecodedBech32(None, None, None),
                         segwit_addr.bech32_decode('mm1crxm3i'))
        self.assertEqual(DecodedBech32(None, None, None),
                         segwit_addr.bech32_decode('au1s5cgom'))
        self.assertEqual(DecodedBech32(None, None, None),
                         segwit_addr.bech32_decode('M1VUXWEZ'))
        self.assertEqual(DecodedBech32(None, None, None),
                         segwit_addr.bech32_decode('16plkw9'))
        self.assertEqual(DecodedBech32(None, None, None),
                         segwit_addr.bech32_decode('1p2gdwpf'))


class Test_bitcoin_testnet(TestCaseForTestnet):

    def test_address_to_script(self):
        # bech32/bech32m native segwit
        # test vectors from BIP-0173
        self.assertEqual(address_to_script('tltc1qrp33g0q5c5txsp9arysrx4k6zdkfs4nce4xj0gdcccefvpysxf3qsnr4fp'), '00201863143c14c5166804bd19203356da136c985678cd4d27a1b8c6329604903262')
        self.assertEqual(address_to_script('tltc1qqqqqp399et2xygdj5xreqhjjvcmzhxw4aywxecjdzew6hylgvsesu9tmgm'), '0020000000c4a5cad46221b2a187905e5266362b99d5e91c6ce24d165dab93e86433')

        # bech32/bech32m native segwit
        # test vectors from BIP-0350
        self.assertEqual(address_to_script('tltc1qrp33g0q5c5txsp9arysrx4k6zdkfs4nce4xj0gdcccefvpysxf3qsnr4fp'), '00201863143c14c5166804bd19203356da136c985678cd4d27a1b8c6329604903262')
        self.assertEqual(address_to_script('tltc1qqqqqp399et2xygdj5xreqhjjvcmzhxw4aywxecjdzew6hylgvsesu9tmgm'), '0020000000c4a5cad46221b2a187905e5266362b99d5e91c6ce24d165dab93e86433')
        self.assertEqual(address_to_script('tltc1pqqqqp399et2xygdj5xreqhjjvcmzhxw4aywxecjdzew6hylgvseskjtjs8'), '5120000000c4a5cad46221b2a187905e5266362b99d5e91c6ce24d165dab93e86433')

        # invalid addresses (from BIP-0173)
        self.assertFalse(is_address('tc1qw508d6qejxtdg4y5r3zarvary0c5xw7kg3g4ty'))
        self.assertFalse(is_address('bc1qw508d6qejxtdg4y5r3zarvary0c5xw7kv8f3t5'))
        self.assertFalse(is_address('LTC13W508D6QEJXTDG4Y5R3ZARVARY0C5XW7KHF4236'))
        self.assertFalse(is_address('ltc1rw58r3kry'))
        self.assertFalse(is_address('ltc10w508d6qejxtdg4y5r3zarvary0c5xw7kw508d6qejxtdg4y5r3zarvary0c5xw7kw5m6y25d'))
        self.assertFalse(is_address('LTC1QR508D6QEJXTDG4Y5R3ZARVARYVQLZUFA'))
        self.assertFalse(is_address('tb1qrp33g0q5c5txsp9arysrx4k6zdkfs4nce4xj0gdcccefvpysxf3q0sL5k7'))
        self.assertFalse(is_address('ltc1zw508d6qejxtdg4y5r3zarvaryvqw53wr5'))
        self.assertFalse(is_address('tltc1qrp33g0q5c5txsp9arysrx4k6zdkfs4nce4xj0gdcccefvpysxf3pd9hq5n'))
        self.assertFalse(is_address('bc1gmk9yu'))

        # invalid addresses (from BIP-0350)
        self.assertFalse(is_address('tc1p0xlxvlhemja6c4dqv22uapctqupfhlxm9h8z3k2e72q4k9hcz7vq5zuyut'))
        self.assertFalse(is_address('ltc1p0xlxvlhemja6c4dqv22uapctqupfhlxm9h8z3k2e72q4k9hcz7vq5w2wdg'))
        self.assertFalse(is_address('tltc1z0xlxvlhemja6c4dqv22uapctqupfhlxm9h8z3k2e72q4k9hcz7vqhuhluk'))
        self.assertFalse(is_address('LTC1S0XLXVLHEMJA6C4DQV22UAPCTQUPFHLXM9H8Z3K2E72Q4K9HCZ7VQH3QF96'))
        self.assertFalse(is_address('ltc1qw508d6qejxtdg4y5r3zarvary0c5xw7ka8rek8'))
        self.assertFalse(is_address('tltc1q0xlxvlhemja6c4dqv22uapctqupfhlxm9h8z3k2e72q4k9hcz7vq4kwe2p'))
        self.assertFalse(is_address('bc1p38j9r5y49hruaue7wxjce0updqjuyyx0kh56v8s25huc6995vvpql3jow4'))
        self.assertFalse(is_address('LTC130XLXVLHEMJA6C4DQV22UAPCTQUPFHLXM9H8Z3K2E72Q4K9HCZ7VQAXQQAX'))
        self.assertFalse(is_address('ltc1pw5kmnaal'))
        self.assertFalse(is_address('ltc1p0xlxvlhemja6c4dqv22uapctqupfhlxm9h8z3k2e72q4k9hcz7v8n0nx0muaewav25f87rvw'))
        self.assertFalse(is_address('LTC1QR508D6QEJXTDG4Y5R3ZARVARYVQLZUFA'))
        self.assertFalse(is_address('tb1p0xlxvlhemja6c4dqv22uapctqupfhlxm9h8z3k2e72q4k9hcz7vq47Zagq'))
        self.assertFalse(is_address('ltc1p0xlxvlhemja6c4dqv22uapctqupfhlxm9h8z3k2e72q4k9hcz7v07q76tu3e'))
        self.assertFalse(is_address('tltc1p0xlxvlhemja6c4dqv22uapctqupfhlxm9h8z3k2e72q4k9hcz7vpht2f2d'))
        self.assertFalse(is_address('bc1gmk9yu'))

        # base58 P2PKH
        self.assertEqual(address_to_script('mutXcGt1CJdkRvXuN2xoz2quAAQYQ59bRX'), '76a9149da64e300c5e4eb4aaffc9c2fd465348d5618ad488ac')
        self.assertEqual(address_to_script('miqtaRTkU3U8rzwKbEHx3g8FSz8GJtPS3K'), '76a914247d2d5b6334bdfa2038e85b20fc15264f8e5d2788ac')

        # base58 P2SH
        self.assertEqual(address_to_script('QWhD3ruwwBHamrNuan4a5M46BpskgXmWih'), 'a9146eae23d8c4a941316017946fc761a7a6c85561fb87')
        self.assertEqual(address_to_script('QhRKknpVnak33GhwHuQ3mCEA7k8F4zxDXG'), 'a914e4567743d378957cd2ee7072da74b1203c1a7a0b87')


class Test_xprv_xpub(ElectrumTestCase):

    xprv_xpub = (
        # Taken from test vectors in https://en.bitcoin.it/wiki/BIP_0032_TestVectors
        {'xprv': 'xprvA41z7zogVVwxVSgdKUHDy1SKmdb533PjDz7J6N6mV6uS3ze1ai8FHa8kmHScGpWmj4WggLyQjgPie1rFSruoUihUZREPSL39UNdE3BBDu76',
         'xpub': 'xpub6H1LXWLaKsWFhvm6RVpEL9P4KfRZSW7abD2ttkWP3SSQvnyA8FSVqNTEcYFgJS2UaFcxupHiYkro49S8yGasTvXEYBVPamhGW6cFJodrTHy',
         'xtype': 'standard'},
        {'xprv': 'yprvAJEYHeNEPcyBoQYM7sGCxDiNCTX65u4ANgZuSGTrKN5YCC9MP84SBayrgaMyZV7zvkHrr3HVPTK853s2SPk4EttPazBZBmz6QfDkXeE8Zr7',
         'xpub': 'ypub6XDth9u8DzXV1tcpDtoDKMf6kVMaVMn1juVWEesTshcX4zUVvfNgjPJLXrD9N7AdTLnbHFL64KmBn3SNaTe69iZYbYCqLCCNPZKbLz9niQ4',
         'xtype': 'p2wpkh-p2sh'},
        {'xprv': 'zprvAWgYBBk7JR8GkraNZJeEodAp2UR1VRWJTXyV1ywuUVs1awUgTiBS1ZTDtLA5F3MFDn1LZzu8dUpSKdT7ToDpvEG6PQu4bJs7zQY47Sd3sEZ',
         'xpub': 'zpub6jftahH18ngZyLeqfLBFAm7YaWFVttE9pku5pNMX2qPzTjoq1FVgZMmhjecyB2nqFb31gHE9vNvbaggU6vvWpNZbXEWLLUjYjFqG95LNyT8',
         'xtype': 'p2wpkh'},
    )

    def _do_test_bip32(self, seed: str, sequence: str):
        node = BIP32Node.from_rootseed(bfh(seed), xtype='standard')
        xprv, xpub = node.to_xprv(), node.to_xpub()
        int_path = convert_bip32_path_to_list_of_uint32(sequence)
        for n in int_path:
            if n & bip32.BIP32_PRIME == 0:
                xpub2 = BIP32Node.from_xkey(xpub).subkey_at_public_derivation([n]).to_xpub()
            node = BIP32Node.from_xkey(xprv).subkey_at_private_derivation([n])
            xprv, xpub = node.to_xprv(), node.to_xpub()
            if n & bip32.BIP32_PRIME == 0:
                self.assertEqual(xpub, xpub2)

        return xpub, xprv

    def test_bip32(self):
        # see https://en.bitcoin.it/wiki/BIP_0032_TestVectors
        # and https://github.com/bitcoin/bips/blob/master/bip-0032.mediawiki#Test_Vectors
        xpub, xprv = self._do_test_bip32("000102030405060708090a0b0c0d0e0f", "m/0'/1/2'/2/1000000000")
        self.assertEqual("xpub6H1LXWLaKsWFhvm6RVpEL9P4KfRZSW7abD2ttkWP3SSQvnyA8FSVqNTEcYFgJS2UaFcxupHiYkro49S8yGasTvXEYBVPamhGW6cFJodrTHy", xpub)
        self.assertEqual("xprvA41z7zogVVwxVSgdKUHDy1SKmdb533PjDz7J6N6mV6uS3ze1ai8FHa8kmHScGpWmj4WggLyQjgPie1rFSruoUihUZREPSL39UNdE3BBDu76", xprv)

        xpub, xprv = self._do_test_bip32("fffcf9f6f3f0edeae7e4e1dedbd8d5d2cfccc9c6c3c0bdbab7b4b1aeaba8a5a29f9c999693908d8a8784817e7b7875726f6c696663605d5a5754514e4b484542","m/0/2147483647'/1/2147483646'/2")
        self.assertEqual("xpub6FnCn6nSzZAw5Tw7cgR9bi15UV96gLZhjDstkXXxvCLsUXBGXPdSnLFbdpq8p9HmGsApME5hQTZ3emM2rnY5agb9rXpVGyy3bdW6EEgAtqt", xpub)
        self.assertEqual("xprvA2nrNbFZABcdryreWet9Ea4LvTJcGsqrMzxHx98MMrotbir7yrKCEXw7nadnHM8Dq38EGfSh6dqA9QWTyefMLEcBYJUuekgW4BYPJcr9E7j", xprv)

        xpub, xprv = self._do_test_bip32("4b381541583be4423346c643850da4b320e46a87ae3d2a4e6da11eba819cd4acba45d239319ac14f863b8d5ab5a0d0c64d2e8a1e7d1457df2e5a3c51c73235be", "m/0h")
        self.assertEqual("xpub68NZiKmJWnxxS6aaHmn81bvJeTESw724CRDs6HbuccFQN9Ku14VQrADWgqbhhTHBaohPX4CjNLf9fq9MYo6oDaPPLPxSb7gwQN3ih19Zm4Y", xpub)
        self.assertEqual("xprv9uPDJpEQgRQfDcW7BkF7eTya6RPxXeJCqCJGHuCJ4GiRVLzkTXBAJMu2qaMWPrS7AANYqdq6vcBcBUdJCVVFceUvJFjaPdGZ2y9WACViL4L", xprv)

        xpub, xprv = self._do_test_bip32("3ddd5602285899a946114506157c7997e5444528f3003f6134712147db19b678", "m/0h/1h")
        self.assertEqual("xpub6BJA1jSqiukeaesWfxe6sNK9CCGaujFFSJLomWHprUL9DePQ4JDkM5d88n49sMGJxrhpjazuXYWdMf17C9T5XnxkopaeS7jGk1GyyVziaMt", xpub)
        self.assertEqual("xprv9xJocDuwtYCMNAo3Zw76WENQeAS6WGXQ55RCy7tDJ8oALr4FWkuVoHJeHVAcAqiZLE7Je3vZJHxspZdFHfnBEjHqU5hG1Jaj32dVoS6XLT1", xprv)

    def test_xpub_from_xprv(self):
        """We can derive the xpub key from a xprv."""
        for xprv_details in self.xprv_xpub:
            result = xpub_from_xprv(xprv_details['xprv'])
            self.assertEqual(result, xprv_details['xpub'])

    def test_is_xpub(self):
        for xprv_details in self.xprv_xpub:
            xpub = xprv_details['xpub']
            self.assertTrue(is_xpub(xpub))
        self.assertFalse(is_xpub('xpub1nval1d'))
        self.assertFalse(is_xpub('xpub661MyMwAqRbcFWohJWt7PHsFEJfZAvw9ZxwQoDa4SoMgsDDM1T7WK3u9E4edkC4ugRnZ8E4xDZRpk8Rnts3Nbt97dPwT52WRONGBADWRONG'))

    def test_xpub_type(self):
        for xprv_details in self.xprv_xpub:
            xpub = xprv_details['xpub']
            self.assertEqual(xprv_details['xtype'], xpub_type(xpub))

    def test_is_xprv(self):
        for xprv_details in self.xprv_xpub:
            xprv = xprv_details['xprv']
            self.assertTrue(is_xprv(xprv))
        self.assertFalse(is_xprv('xprv1nval1d'))
        self.assertFalse(is_xprv('xprv661MyMwAqRbcFWohJWt7PHsFEJfZAvw9ZxwQoDa4SoMgsDDM1T7WK3u9E4edkC4ugRnZ8E4xDZRpk8Rnts3Nbt97dPwT52WRONGBADWRONG'))

    def test_is_bip32_derivation(self):
        self.assertTrue(is_bip32_derivation("m/0'/1"))
        self.assertTrue(is_bip32_derivation("m/0'/0'"))
        self.assertTrue(is_bip32_derivation("m/3'/-5/8h/"))
        self.assertTrue(is_bip32_derivation("m/44'/0'/0'/0/0"))
        self.assertTrue(is_bip32_derivation("m/49'/0'/0'/0/0"))
        self.assertTrue(is_bip32_derivation("m"))
        self.assertTrue(is_bip32_derivation("m/"))
        self.assertFalse(is_bip32_derivation("m5"))
        self.assertFalse(is_bip32_derivation("mmmmmm"))
        self.assertFalse(is_bip32_derivation("n/"))
        self.assertFalse(is_bip32_derivation(""))
        self.assertFalse(is_bip32_derivation("m/q8462"))
        self.assertFalse(is_bip32_derivation("m/-8h"))

    def test_convert_bip32_path_to_list_of_uint32(self):
        self.assertEqual([0, 0x80000001, 0x80000001], convert_bip32_path_to_list_of_uint32("m/0/-1/1'"))
        self.assertEqual([], convert_bip32_path_to_list_of_uint32("m/"))
        self.assertEqual([2147483692, 2147488889, 221], convert_bip32_path_to_list_of_uint32("m/44'/5241h/221"))

    def test_convert_bip32_intpath_to_strpath(self):
        self.assertEqual("m/0/1'/1'", convert_bip32_intpath_to_strpath([0, 0x80000001, 0x80000001]))
        self.assertEqual("m", convert_bip32_intpath_to_strpath([]))
        self.assertEqual("m/44'/5241'/221", convert_bip32_intpath_to_strpath([2147483692, 2147488889, 221]))

    def test_normalize_bip32_derivation(self):
        self.assertEqual("m/0/1'/1'", normalize_bip32_derivation("m/0/1h/1'"))
        self.assertEqual("m", normalize_bip32_derivation("m////"))
        self.assertEqual("m/0/2/1'", normalize_bip32_derivation("m/0/2/-1/"))
        self.assertEqual("m/0/1'/1'/5'", normalize_bip32_derivation("m/0//-1/1'///5h"))

    def test_is_xkey_consistent_with_key_origin_info(self):
        ### actual data (high depth path)
        self.assertTrue(bip32.is_xkey_consistent_with_key_origin_info(
            "Zpub75NQordWKAkaF7utBw95GEodyxqwFdR3idtTqQtrvWkYFeiuYdg5c3Q9L9bLjPLhEahLCTjmmS2YQcXPwr6twYCEJ55k6uhE5JxRqvUowmd",
            derivation_prefix="m/48'/1'/0'/2'",
            root_fingerprint="b2768d2f"))
        # ok to skip args
        self.assertTrue(bip32.is_xkey_consistent_with_key_origin_info(
            "Zpub75NQordWKAkaF7utBw95GEodyxqwFdR3idtTqQtrvWkYFeiuYdg5c3Q9L9bLjPLhEahLCTjmmS2YQcXPwr6twYCEJ55k6uhE5JxRqvUowmd",
            derivation_prefix="m/48'/1'/0'/2'"))
        self.assertTrue(bip32.is_xkey_consistent_with_key_origin_info(
            "Zpub75NQordWKAkaF7utBw95GEodyxqwFdR3idtTqQtrvWkYFeiuYdg5c3Q9L9bLjPLhEahLCTjmmS2YQcXPwr6twYCEJ55k6uhE5JxRqvUowmd",
            root_fingerprint="b2768d2f"))
        # path changed: wrong depth
        self.assertFalse(bip32.is_xkey_consistent_with_key_origin_info(
            "Zpub75NQordWKAkaF7utBw95GEodyxqwFdR3idtTqQtrvWkYFeiuYdg5c3Q9L9bLjPLhEahLCTjmmS2YQcXPwr6twYCEJ55k6uhE5JxRqvUowmd",
            derivation_prefix="m/48'/0'/2'",
            root_fingerprint="b2768d2f"))
        # path changed: wrong child index
        self.assertFalse(bip32.is_xkey_consistent_with_key_origin_info(
            "Zpub75NQordWKAkaF7utBw95GEodyxqwFdR3idtTqQtrvWkYFeiuYdg5c3Q9L9bLjPLhEahLCTjmmS2YQcXPwr6twYCEJ55k6uhE5JxRqvUowmd",
            derivation_prefix="m/48'/1'/0'/3'",
            root_fingerprint="b2768d2f"))
        # path changed: but cannot tell
        self.assertTrue(bip32.is_xkey_consistent_with_key_origin_info(
            "Zpub75NQordWKAkaF7utBw95GEodyxqwFdR3idtTqQtrvWkYFeiuYdg5c3Q9L9bLjPLhEahLCTjmmS2YQcXPwr6twYCEJ55k6uhE5JxRqvUowmd",
            derivation_prefix="m/48'/1'/1'/2'",
            root_fingerprint="b2768d2f"))
        # fp changed: but cannot tell
        self.assertTrue(bip32.is_xkey_consistent_with_key_origin_info(
            "Zpub75NQordWKAkaF7utBw95GEodyxqwFdR3idtTqQtrvWkYFeiuYdg5c3Q9L9bLjPLhEahLCTjmmS2YQcXPwr6twYCEJ55k6uhE5JxRqvUowmd",
            derivation_prefix="m/48'/1'/0'/2'",
            root_fingerprint="aaaaaaaa"))

        ### actual data (depth=1 path)
        self.assertTrue(bip32.is_xkey_consistent_with_key_origin_info(
            "zpub6nsHdRuY92FsMKdbn9BfjBCG6X8pyhCibNP6uDvpnw2cyrVhecvHRMa3Ne8kdJZxjxgwnpbHLkcR4bfnhHy6auHPJyDTQ3kianeuVLdkCYQ",
            derivation_prefix="m/0'",
            root_fingerprint="b2e35a7d"))
        # path changed: wrong depth
        self.assertFalse(bip32.is_xkey_consistent_with_key_origin_info(
            "zpub6nsHdRuY92FsMKdbn9BfjBCG6X8pyhCibNP6uDvpnw2cyrVhecvHRMa3Ne8kdJZxjxgwnpbHLkcR4bfnhHy6auHPJyDTQ3kianeuVLdkCYQ",
            derivation_prefix="m/0'/0'",
            root_fingerprint="b2e35a7d"))
        # path changed: wrong child index
        self.assertFalse(bip32.is_xkey_consistent_with_key_origin_info(
            "zpub6nsHdRuY92FsMKdbn9BfjBCG6X8pyhCibNP6uDvpnw2cyrVhecvHRMa3Ne8kdJZxjxgwnpbHLkcR4bfnhHy6auHPJyDTQ3kianeuVLdkCYQ",
            derivation_prefix="m/1'",
            root_fingerprint="b2e35a7d"))
        # fp changed: can tell
        self.assertFalse(bip32.is_xkey_consistent_with_key_origin_info(
            "zpub6nsHdRuY92FsMKdbn9BfjBCG6X8pyhCibNP6uDvpnw2cyrVhecvHRMa3Ne8kdJZxjxgwnpbHLkcR4bfnhHy6auHPJyDTQ3kianeuVLdkCYQ",
            derivation_prefix="m/0'",
            root_fingerprint="aaaaaaaa"))

        ### actual data (depth=0 path)
        self.assertTrue(bip32.is_xkey_consistent_with_key_origin_info(
            "xpub661MyMwAqRbcFWohJWt7PHsFEJfZAvw9ZxwQoDa4SoMgsDDM1T7WK3u9E4edkC4ugRnZ8E4xDZRpk8Rnts3Nbt97dPwT52CwBdDWroaZf8U",
            derivation_prefix="m",
            root_fingerprint="48adc7a0"))
        # path changed: wrong depth
        self.assertFalse(bip32.is_xkey_consistent_with_key_origin_info(
            "xpub661MyMwAqRbcFWohJWt7PHsFEJfZAvw9ZxwQoDa4SoMgsDDM1T7WK3u9E4edkC4ugRnZ8E4xDZRpk8Rnts3Nbt97dPwT52CwBdDWroaZf8U",
            derivation_prefix="m/0",
            root_fingerprint="48adc7a0"))
        # fp changed: can tell
        self.assertFalse(bip32.is_xkey_consistent_with_key_origin_info(
            "xpub661MyMwAqRbcFWohJWt7PHsFEJfZAvw9ZxwQoDa4SoMgsDDM1T7WK3u9E4edkC4ugRnZ8E4xDZRpk8Rnts3Nbt97dPwT52CwBdDWroaZf8U",
            derivation_prefix="m",
            root_fingerprint="aaaaaaaa"))

    def test_is_all_public_derivation(self):
        self.assertFalse(is_all_public_derivation("m/0/1'/1'"))
        self.assertFalse(is_all_public_derivation("m/0/2/1'"))
        self.assertFalse(is_all_public_derivation("m/0/1'/1'/5"))
        self.assertTrue(is_all_public_derivation("m"))
        self.assertTrue(is_all_public_derivation("m/0"))
        self.assertTrue(is_all_public_derivation("m/75/22/3"))

    def test_xtype_from_derivation(self):
        self.assertEqual('standard', xtype_from_derivation("m/44'"))
        self.assertEqual('standard', xtype_from_derivation("m/44'/"))
        self.assertEqual('standard', xtype_from_derivation("m/44'/0'/0'"))
        self.assertEqual('standard', xtype_from_derivation("m/44'/5241'/221"))
        self.assertEqual('standard', xtype_from_derivation("m/45'"))
        self.assertEqual('standard', xtype_from_derivation("m/45'/56165/271'"))
        self.assertEqual('p2wpkh-p2sh', xtype_from_derivation("m/49'"))
        self.assertEqual('p2wpkh-p2sh', xtype_from_derivation("m/49'/134"))
        self.assertEqual('p2wpkh', xtype_from_derivation("m/84'"))
        self.assertEqual('p2wpkh', xtype_from_derivation("m/84'/112'/992/112/33'/0/2"))
        self.assertEqual('p2wsh-p2sh', xtype_from_derivation("m/48'/0'/0'/1'"))
        self.assertEqual('p2wsh-p2sh', xtype_from_derivation("m/48'/0'/0'/1'/52112/52'"))
        self.assertEqual('p2wsh-p2sh', xtype_from_derivation("m/48'/9'/2'/1'"))
        self.assertEqual('p2wsh', xtype_from_derivation("m/48'/0'/0'/2'"))
        self.assertEqual('p2wsh', xtype_from_derivation("m/48'/1'/0'/2'/77'/0"))

    def test_version_bytes(self):
        xprv_headers_b58 = {
            'standard':    'xprv',
            'p2wpkh-p2sh': 'yprv',
            'p2wsh-p2sh':  'Yprv',
            'p2wpkh':      'zprv',
            'p2wsh':       'Zprv',
        }
        xpub_headers_b58 = {
            'standard':    'xpub',
            'p2wpkh-p2sh': 'ypub',
            'p2wsh-p2sh':  'Ypub',
            'p2wpkh':      'zpub',
            'p2wsh':       'Zpub',
        }
        for xtype, xkey_header_bytes in constants.net.XPRV_HEADERS.items():
            xkey_header_bytes = bfh("%08x" % xkey_header_bytes)
            xkey_bytes = xkey_header_bytes + bytes([0] * 74)
            xkey_b58 = EncodeBase58Check(xkey_bytes)
            self.assertTrue(xkey_b58.startswith(xprv_headers_b58[xtype]))

            xkey_bytes = xkey_header_bytes + bytes([255] * 74)
            xkey_b58 = EncodeBase58Check(xkey_bytes)
            self.assertTrue(xkey_b58.startswith(xprv_headers_b58[xtype]))

        for xtype, xkey_header_bytes in constants.net.XPUB_HEADERS.items():
            xkey_header_bytes = bfh("%08x" % xkey_header_bytes)
            xkey_bytes = xkey_header_bytes + bytes([0] * 74)
            xkey_b58 = EncodeBase58Check(xkey_bytes)
            self.assertTrue(xkey_b58.startswith(xpub_headers_b58[xtype]))

            xkey_bytes = xkey_header_bytes + bytes([255] * 74)
            xkey_b58 = EncodeBase58Check(xkey_bytes)
            self.assertTrue(xkey_b58.startswith(xpub_headers_b58[xtype]))


class Test_xprv_xpub_testnet(TestCaseForTestnet):

    def test_version_bytes(self):
        xprv_headers_b58 = {
            'standard':    'tprv',
            'p2wpkh-p2sh': 'uprv',
            'p2wsh-p2sh':  'Uprv',
            'p2wpkh':      'vprv',
            'p2wsh':       'Vprv',
        }
        xpub_headers_b58 = {
            'standard':    'tpub',
            'p2wpkh-p2sh': 'upub',
            'p2wsh-p2sh':  'Upub',
            'p2wpkh':      'vpub',
            'p2wsh':       'Vpub',
        }
        for xtype, xkey_header_bytes in constants.net.XPRV_HEADERS.items():
            xkey_header_bytes = bfh("%08x" % xkey_header_bytes)
            xkey_bytes = xkey_header_bytes + bytes([0] * 74)
            xkey_b58 = EncodeBase58Check(xkey_bytes)
            self.assertTrue(xkey_b58.startswith(xprv_headers_b58[xtype]))

            xkey_bytes = xkey_header_bytes + bytes([255] * 74)
            xkey_b58 = EncodeBase58Check(xkey_bytes)
            self.assertTrue(xkey_b58.startswith(xprv_headers_b58[xtype]))

        for xtype, xkey_header_bytes in constants.net.XPUB_HEADERS.items():
            xkey_header_bytes = bfh("%08x" % xkey_header_bytes)
            xkey_bytes = xkey_header_bytes + bytes([0] * 74)
            xkey_b58 = EncodeBase58Check(xkey_bytes)
            self.assertTrue(xkey_b58.startswith(xpub_headers_b58[xtype]))

            xkey_bytes = xkey_header_bytes + bytes([255] * 74)
            xkey_b58 = EncodeBase58Check(xkey_bytes)
            self.assertTrue(xkey_b58.startswith(xpub_headers_b58[xtype]))


class Test_keyImport(ElectrumTestCase):

    priv_pub_addr = (
           {'priv': 'T6BXB6VCkmZEWm9wkG4TLWrhgbTVWtSDHfj42gzdk1UKAt3qZMPk',
            'exported_privkey': 'p2pkh:T6BXB6VCkmZEWm9wkG4TLWrhgbTVWtSDHfj42gzdk1UKAt3qZMPk',
            'pub': '02c6467b7e621144105ed3e4835b0b4ab7e35266a2ae1c4f8baa19e9ca93452997',
            'address': 'LRox6fSH5krrgaCUiPiLkm458B5pyG8vxq',
            'minikey' : False,
            'txin_type': 'p2pkh',
            'compressed': True,
            'addr_encoding': 'base58',
            'scripthash': 'c9aecd1fef8d661a42c560bf75c8163e337099800b8face5ca3d1393a30508a7'},
           {'priv': 'p2pkh:T6ZPwVEzxX8CBg8X2MNQ4gSu6czA5t7mLA9c3ywKaswMZ1hNKvVZ',
            'exported_privkey': 'p2pkh:T6ZPwVEzxX8CBg8X2MNQ4gSu6czA5t7mLA9c3ywKaswMZ1hNKvVZ',
            'pub': '0352d78b4b37e0f6d4e164423436f2925fa57817467178eca550a88f2821973c41',
            'address': 'LakdpHiYBM1ai6BbzcNrcz7xvF9soBMCgH',
            'minikey': False,
            'txin_type': 'p2pkh',
            'compressed': True,
            'addr_encoding': 'base58',
            'scripthash': 'a9b2a76fc196c553b352186dfcca81fcf323a721cd8431328f8e9d54216818c1'},
           {'priv': '6uGWYKbyKLBMa1ysfq9rMANcbtYKY49vrawvaH3rBXooApLq6t2',
            'exported_privkey': 'p2pkh:6uGWYKbyKLBMa1ysfq9rMANcbtYKY49vrawvaH3rBXooApLq6t2',
            'pub': '04e5fe91a20fac945845a5518450d23405ff3e3e1ce39827b47ee6d5db020a9075422d56a59195ada0035e4a52a238849f68e7a325ba5b2247013e0481c5c7cb3f',
            'address': 'LacEkfqxYsPqDuS8ZCstJUc59gxVm2DQaT',
            'minikey': False,
            'txin_type': 'p2pkh',
            'compressed': False,
            'addr_encoding': 'base58',
            'scripthash': 'f5914651408417e1166f725a5829ff9576d0dbf05237055bf13abd2af7f79473'},
           {'priv': 'p2pkh:6w1GsLBYs3YYWGjgHb4nFtzzBP24MwNpbH7N5QxP6dGdqTbGHD8',
            'exported_privkey': 'p2pkh:6w1GsLBYs3YYWGjgHb4nFtzzBP24MwNpbH7N5QxP6dGdqTbGHD8',
            'pub': '048f0431b0776e8210376c81280011c2b68be43194cb00bd47b7e9aa66284b713ce09556cde3fee606051a07613f3c159ef3953b8927c96ae3dae94a6ba4182e0e',
            'address': 'LNLhydb7qoutuA6bryeN249JD7scUTtDQq',
            'minikey': False,
            'txin_type': 'p2pkh',
            'compressed': False,
            'addr_encoding': 'base58',
            'scripthash': '6dd2e07ad2de9ba8eec4bbe8467eb53f8845acff0d9e6f5627391acc22ff62df'},
           {'priv': 'LHJnnvRzsdrTX2j5QeWVsaBkabK7gfMNqNNqxnbBVRaJYfk24iJz',
            'exported_privkey': 'p2wpkh-p2sh:T5yo6M1NvhznLqLQr8faVaYA2aZ85uppKh2qhgXY5SF3VtrUxS4V',
            'pub': '0279ad237ca0d812fb503ab86f25e15ebd5fa5dd95c193639a8a738dcd1acbad81',
            'address': 'MNrdc4TmGxyFgBbKC4SsGbaHqBM7uzsjTf',
            'minikey': False,
            'txin_type': 'p2wpkh-p2sh',
            'compressed': True,
            'addr_encoding': 'base58',
            'scripthash': 'd7b04e882fa6b13246829ac552a2b21461d9152eb00f0a6adb58457a3e63d7c5'},
           {'priv': 'p2wpkh-p2sh:T92pim7wXVVfNRryK5Dnn8hvxBFZHWpf17XjcfNiq5QjD7Qkyitu',
            'exported_privkey': 'p2wpkh-p2sh:T92pim7wXVVfNRryK5Dnn8hvxBFZHWpf17XjcfNiq5QjD7Qkyitu',
            'pub': '0229da20a15b3363b2c28e3c5093c180b56c439df0b968a970366bb1f38435361e',
            'address': 'MJKHzgmuQEqsGEogVgC1v8VfVV5GVjm822',
            'minikey': False,
            'txin_type': 'p2wpkh-p2sh',
            'compressed': True,
            'addr_encoding': 'base58',
            'scripthash': '714bf6bfe1083e69539f40d4c7a7dca85d187471b35642e55f20d7e866494cf7'},
           {'priv': 'L8g5V8kFFeg2WbecahRSdobARbHz2w2STH9S8ePHVSY4fmia7Rsj',
            'exported_privkey': 'p2wpkh:T5viMigXUsjVJvGiaFyR3z3481jeGbmc73RZRzfjZvxWuL2E1FGB',
            'pub': '03e9f948421aaa89415dc5f281a61b60dde12aae3181b3a76cd2d849b164fc6d0b',
            'address': 'ltc1qqmpt7u5e9hfznljta5gnvhyvfd2kdd0rpnd2yf',
            'minikey': False,
            'txin_type': 'p2wpkh',
            'compressed': True,
            'addr_encoding': 'bech32',
            'scripthash': '1929acaaef3a208c715228e9f1ca0318e3a6b9394ab53c8d026137f847ecf97b'},
           {'priv': 'p2wpkh:T53nQpon8i8fuQHkEejzyQMYA8Gc813w2XeKcvKfkBG9jCjWvCGN',
            'exported_privkey': 'p2wpkh:T53nQpon8i8fuQHkEejzyQMYA8Gc813w2XeKcvKfkBG9jCjWvCGN',
            'pub': '038c57657171c1f73e34d5b3971d05867d50221ad94980f7e87cbc2344425e6a1e',
            'address': 'ltc1qpakeeg4d9ydyjxd8paqrw4xy9htsg532z7uhvl',
            'minikey': False,
            'txin_type': 'p2wpkh',
            'compressed': True,
            'addr_encoding': 'bech32',
            'scripthash': '242f02adde84ebb2a7dd778b2f3a81b3826f111da4d8960d826d7a4b816cb261'},
           # from http://bitscan.com/articles/security/spotlight-on-mini-private-keys
           {'priv': 'SzavMBLoXU6kDrqtUVmffv',
            'exported_privkey': 'p2pkh:6vtsDUCgu6yHGBaa92x4skmZHa2LmMz4sNuh54tUhqJFELE28eh',
            'pub': '04588d202afcc1ee4ab5254c7847ec25b9a135bbda0f2bc69ee1a714749fd77dc9f88ff2a00d7e752d44cbe16e1ebcf0890b76ec7c78886109dee76ccfc8445424',
            'address': 'LWQznEzj9nsACLAfXof8C1RuWP2jWp7MwM',
            'minikey': True,
            'txin_type': 'p2pkh',
            'compressed': False,  # this is actually ambiguous... issue #2748
            'addr_encoding': 'base58',
            'scripthash': '5b07ddfde826f5125ee823900749103cea37808038ecead5505a766a07c34445'},
    )

    def test_public_key_from_private_key(self):
        for priv_details in self.priv_pub_addr:
            txin_type, privkey, compressed = deserialize_privkey(priv_details['priv'])
            result = ecc.ECPrivkey(privkey).get_public_key_hex(compressed=compressed)
            self.assertEqual(priv_details['pub'], result)
            self.assertEqual(priv_details['txin_type'], txin_type)
            self.assertEqual(priv_details['compressed'], compressed)

    def test_address_from_private_key(self):
        for priv_details in self.priv_pub_addr:
            addr2 = address_from_private_key(priv_details['priv'])
            self.assertEqual(priv_details['address'], addr2)

    def test_is_valid_address(self):
        for priv_details in self.priv_pub_addr:
            addr = priv_details['address']
            self.assertFalse(is_address(priv_details['priv']))
            self.assertFalse(is_address(priv_details['pub']))
            self.assertTrue(is_address(addr))

            is_enc_b58 = priv_details['addr_encoding'] == 'base58'
            self.assertEqual(is_enc_b58, is_b58_address(addr))

            is_enc_bech32 = priv_details['addr_encoding'] == 'bech32'
            self.assertEqual(is_enc_bech32, is_segwit_address(addr))

        self.assertFalse(is_address("not an address"))

    def test_is_address_bad_checksums(self):
        self.assertTrue(is_address('LSE78Hmo3FRxAE61DyYB2NYxM5xHtpZPJ1'))
        self.assertFalse(is_address('LSE78Hmo3FRxAE61DyYB2NYxM5xHtpZPJ2'))

        self.assertTrue(is_address('MT4sePCkdxe17A4wHHvh1KHU3Y9KjZbpsQ'))
        self.assertFalse(is_address('MT4sePCkdxe17A4wHHvh1KHU3Y9KjZbpsP'))

        self.assertTrue(is_address('ltc1qxq64lrwt02hm7tu25lr3hm9tgzh58snfaxyqn2'))
        self.assertFalse(is_address('ltc1qxq64lrwt02hm7tu25lr3hm9tgzh58snfaxyqn1'))

    def test_is_private_key(self):
        for priv_details in self.priv_pub_addr:
            self.assertTrue(is_private_key(priv_details['priv']))
            self.assertTrue(is_private_key(priv_details['exported_privkey']))
            self.assertFalse(is_private_key(priv_details['pub']))
            self.assertFalse(is_private_key(priv_details['address']))
        self.assertFalse(is_private_key("not a privkey"))

    def test_serialize_privkey(self):
        for priv_details in self.priv_pub_addr:
            txin_type, privkey, compressed = deserialize_privkey(priv_details['priv'])
            priv2 = serialize_privkey(privkey, compressed, txin_type)
            self.assertEqual(priv_details['exported_privkey'], priv2)

    def test_address_to_scripthash(self):
        for priv_details in self.priv_pub_addr:
            sh = address_to_scripthash(priv_details['address'])
            self.assertEqual(priv_details['scripthash'], sh)

    def test_is_minikey(self):
        for priv_details in self.priv_pub_addr:
            minikey = priv_details['minikey']
            priv = priv_details['priv']
            self.assertEqual(minikey, is_minikey(priv))

    def test_is_compressed_privkey(self):
        for priv_details in self.priv_pub_addr:
            self.assertEqual(priv_details['compressed'],
                             is_compressed_privkey(priv_details['priv']))

    def test_segwit_uncompressed_pubkey(self):
        with self.assertRaises(BitcoinException):
            is_private_key("p2wpkh-p2sh:6udGRabU4ykVSyC14CYs5JdKtHTa7hcpaXaerM9xDQayw9V3r76",
                           raise_on_error=True)

    def test_wif_with_invalid_magic_byte_for_compressed_pubkey(self):
        with self.assertRaises(BitcoinException):
            is_private_key("T35S1qU6BBimysGNP3HG2FbQg9Mox1UbMDgGw5vfsgJakYaq8SfU",
                           raise_on_error=True)


class TestBaseEncode(ElectrumTestCase):

    def test_base43(self):
        tx_hex = "020000000001021cd0e96f9ca202e017ca3465e3c13373c0df3a4cdd91c1fd02ea42a1a65d2a410000000000fdffffff757da7cf8322e5063785e2d8ada74702d2648fa2add2d533ba83c52eb110df690200000000fdffffff02d07e010000000000160014b544c86eaf95e3bb3b6d2cabb12ab40fc59cad9ca086010000000000232102ce0d066fbfcf150a5a1bbc4f312cd2eb080e8d8a47e5f2ce1a63b23215e54fb5ac02483045022100a9856bf10a950810abceeabc9a86e6ba533e130686e3d7863971b9377e7c658a0220288a69ef2b958a7c2ecfa376841d4a13817ed24fa9a0e0a6b9cb48e6439794c701210324e291735f83ff8de47301b12034950b80fa4724926a34d67e413d8ff8817c53024830450221008f885978f7af746679200ed55fe2e86c1303620824721f95cc41eb7965a3dfcf02207872082ac4a3c433d41a203e6d685a459e70e551904904711626ac899238c20a0121023d4c9deae1aacf3f822dd97a28deaec7d4e4ff97be746d124a63d20e582f5b290a971600"
        tx_bytes = bfh(tx_hex)
        tx_base43 = base_encode(tx_bytes, base=43)
        self.assertEqual("3E2DH7.J3PKVZJ3RCOXQVS3Y./6-WE.75DDU0K58-0N1FRL565N8ZH-DG1Z.1IGWTE5HK8F7PWH5P8+V3XGZZ6GQBPHNDE+RD8CAQVV1/6PQEMJIZTGPMIJ93B8P$QX+Y2R:TGT9QW8S89U4N2.+FUT8VG+34USI/N/JJ3CE*KLSW:REE8T5Y*9:U6515JIUR$6TODLYHSDE3B5DAF:5TF7V*VAL3G40WBOM0DO2+CFKTTM$G-SO:8U0EW:M8V:4*R9ZDX$B1IRBP9PLMDK8H801PNTFB4$HL1+/U3F61P$4N:UAO88:N5D+J:HI4YR8IM:3A7K1YZ9VMRC/47$6GGW5JEL1N690TDQ4XW+TWHD:V.1.630QK*JN/.EITVU80YS3.8LWKO:2STLWZAVHUXFHQ..NZ0:.J/FTZM.KYDXIE1VBY7/:PHZMQ$.JZQ2.XT32440X/HM+UY/7QP4I+HTD9.DUSY-8R6HDR-B8/PF2NP7I2-MRW9VPW3U9.S0LQ.*221F8KVMD5ANJXZJ8WV4UFZ4R.$-NXVE+-FAL:WFERGU+WHJTHAP",
                         tx_base43)
        self.assertEqual(tx_bytes,
                         base_decode(tx_base43, base=43))

    def test_base58(self):
        data_hex = '0cd394bef396200774544c58a5be0189f3ceb6a41c8da023b099ce547dd4d8071ed6ed647259fba8c26382edbf5165dfd2404e7a8885d88437db16947a116e451a5d1325e3fd075f9d370120d2ab537af69f32e74fc0ba53aaaa637752964b3ac95cfea7'
        data_bytes = bfh(data_hex)
        data_base58 = base_encode(data_bytes, base=58)
        self.assertEqual("VuvZ2K5UEcXCVcogny7NH4Evd9UfeYipsTdWuU4jLDhyaESijKtrGWZTFzVZJPjaoC9jFBs3SFtarhDhQhAxkXosUD8PmUb5UXW1tafcoPiCp8jHy7Fe2CUPXAbYuMvAyrkocbe6",
                         data_base58)
        self.assertEqual(data_bytes,
                         base_decode(data_base58, base=58))

    def test_base58check(self):
        data_hex = '0cd394bef396200774544c58a5be0189f3ceb6a41c8da023b099ce547dd4d8071ed6ed647259fba8c26382edbf5165dfd2404e7a8885d88437db16947a116e451a5d1325e3fd075f9d370120d2ab537af69f32e74fc0ba53aaaa637752964b3ac95cfea7'
        data_bytes = bfh(data_hex)
        data_base58check = EncodeBase58Check(data_bytes)
        self.assertEqual("4GCCJsjHqFbHxWbFBvRg35cSeNLHKeNqkXqFHW87zRmz6iP1dJU9Tk2KHZkoKj45jzVsSV4ZbQ8GpPwko6V3Z7cRfux3zJhUw7TZB6Kpa8Vdya8cMuUtL5Ry3CLtMetaY42u52X7Ey6MAH",
                         data_base58check)
        self.assertEqual(data_bytes,
                         DecodeBase58Check(data_base58check))
