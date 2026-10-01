package com.toma.companion

import java.net.URI

data class PairingInfo(val address: String, val fingerprint: String)

object Pairing {
    private const val HEADER = "TOMADESK-PAIR-V1"
    private val fingerprintPattern = Regex("[0-9A-F]{64}")

    fun parse(raw: String): PairingInfo {
        require(raw.length <= 512) { "토마데스크 연결 QR이 아닙니다." }
        val lines = raw.split('\n')
        require(lines.size == 3 && lines[0] == HEADER) { "토마데스크 연결 QR이 아닙니다." }
        val uri = try { URI(lines[1]) } catch (_: Exception) {
            throw IllegalArgumentException("PC 연결 주소가 올바르지 않습니다.")
        }
        require(uri.scheme == "https" && uri.port == 47831 && uri.userInfo == null &&
            uri.rawPath.isNullOrEmpty() && uri.rawQuery == null && uri.rawFragment == null &&
            uri.toString() == lines[1]) { "PC 연결 주소가 올바르지 않습니다." }
        val parts = (uri.host ?: "").split('.')
        require(parts.size == 4 && parts.all { it.isNotEmpty() && it.all(Char::isDigit) &&
            (it == "0" || !it.startsWith('0')) && (it.toIntOrNull()?.let { value -> value in 0..255 } == true) }) {
            "PC의 Tailscale IPv4 주소가 아닙니다."
        }
        require(parts[0] == "100" && parts[1].toInt() in 64..127) {
            "PC의 Tailscale IPv4 주소가 아닙니다."
        }
        require(fingerprintPattern.matches(lines[2])) { "PC 인증서 지문이 올바르지 않습니다." }
        return PairingInfo(lines[1], lines[2])
    }
}
