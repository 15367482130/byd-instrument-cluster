package com.wb.bydfeipin;

import android.util.Base64;

import java.math.BigInteger;
import java.security.KeyFactory;
import java.security.KeyPair;
import java.security.KeyPairGenerator;
import java.security.PrivateKey;
import java.security.interfaces.RSAPublicKey;
import java.security.spec.PKCS8EncodedKeySpec;

import javax.crypto.Cipher;

/**
 * ADB 授权用的 RSA 密钥工具。
 *
 * <p>Android 的 adbd 使用一套自定义公钥格式（见 AOSP
 * libcrypto_utils/android_pubkey.c 的 RSAPublicKey 结构）：
 *
 * <pre>
 *   uint32 modulus_size_words;          // = 2048/8/4 = 64
 *   uint32 n0inv;                       // -1 / n[0] mod 2^32
 *   uint8  modulus[256];                // 小端
 *   uint8  rr[256];                     // (2^2048)^2 mod n，小端
 *   uint32 exponent;                    // 65537
 * </pre>
 *
 * 共 524 字节，Base64 后再加 " user@host" 即为 AUTH 包要发送的公钥串。
 *
 * <p>签名：ADB 对 20 字节 token 做的是 RSA PKCS#1 v1.5 + SHA-1 的
 * <b>预哈希</b>模式（token 直接当作 SHA-1 摘要），因此要用
 * {@code RSA/ECB/PKCS1Padding} 加密 {@code SHA1_DigestInfo || token}。
 */
public final class RsaKeyUtil {

    private static final int MODULUS_SIZE = 256;               // 2048 / 8
    private static final int MODULUS_SIZE_WORDS = MODULUS_SIZE / 4;

    /** SHA-1 的 DigestInfo ASN.1 前缀（RFC 3447）。 */
    private static final byte[] SHA1_DIGEST_INFO = {
        0x30, 0x21, 0x30, 0x09, 0x06, 0x05, 0x2b, 0x0e,
        0x03, 0x02, 0x1a, 0x05, 0x00, 0x04, 0x14
    };

    private RsaKeyUtil() {}

    public static KeyPair generateKeyPair() throws Exception {
        KeyPairGenerator gen = KeyPairGenerator.getInstance("RSA");
        gen.initialize(2048);
        return gen.generateKeyPair();
    }

    public static PrivateKey loadPrivateKey(byte[] pkcs8) throws Exception {
        return KeyFactory.getInstance("RSA").generatePrivate(new PKCS8EncodedKeySpec(pkcs8));
    }

    /** 构造 adbd 需要的公钥字符串（Base64(524字节) + " user@host"）。 */
    public static String buildPublicKeyString(RSAPublicKey pub) {
        BigInteger n = pub.getModulus();
        BigInteger e = pub.getPublicExponent();

        BigInteger r32 = BigInteger.ONE.shiftLeft(32);
        // n0inv = 2^32 - (n^-1 mod 2^32)
        BigInteger n0inv = r32.subtract(n.mod(r32).modInverse(r32));
        // rr = (2^2048)^2 mod n
        BigInteger two2048 = BigInteger.ONE.shiftLeft(MODULUS_SIZE * 8);
        BigInteger rr = two2048.multiply(two2048).mod(n);

        byte[] out = new byte[524];
        int p = 0;
        p = putUint32LE(out, p, MODULUS_SIZE_WORDS);
        p = putUint32LE(out, p, (int) (n0inv.longValue() & 0xFFFFFFFFL));
        p = putBigIntLE(out, p, n, MODULUS_SIZE);
        p = putBigIntLE(out, p, rr, MODULUS_SIZE);
        p = putUint32LE(out, p, (int) (e.longValue() & 0xFFFFFFFFL));

        return Base64.encodeToString(out, Base64.NO_WRAP) + " bydfeipin@android";
    }

    /** 对 ADB 的 20 字节 token 签名。 */
    public static byte[] signToken(PrivateKey key, byte[] token) throws Exception {
        byte[] data = new byte[SHA1_DIGEST_INFO.length + token.length];
        System.arraycopy(SHA1_DIGEST_INFO, 0, data, 0, SHA1_DIGEST_INFO.length);
        System.arraycopy(token, 0, data, SHA1_DIGEST_INFO.length, token.length);

        Cipher cipher = Cipher.getInstance("RSA/ECB/PKCS1Padding");
        cipher.init(Cipher.ENCRYPT_MODE, key);
        return cipher.doFinal(data);
    }

    // ---- 小工具 ----

    private static int putUint32LE(byte[] b, int off, int v) {
        b[off] = (byte) (v & 0xFF);
        b[off + 1] = (byte) ((v >>> 8) & 0xFF);
        b[off + 2] = (byte) ((v >>> 16) & 0xFF);
        b[off + 3] = (byte) ((v >>> 24) & 0xFF);
        return off + 4;
    }

    /** 把 BigInteger 写成固定长度的小端字节。 */
    private static int putBigIntLE(byte[] b, int off, BigInteger v, int size) {
        byte[] be = v.toByteArray();          // 大端，可能带 0x00 符号位
        for (int i = 0; i < size; i++) {
            int src = be.length - 1 - i;
            b[off + i] = src >= 0 ? be[src] : 0;
        }
        return off + size;
    }
}
