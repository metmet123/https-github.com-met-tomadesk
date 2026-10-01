package com.toma.companion

import java.net.URI

data class PairingInfo(val address: String)

object Pairing {
    fun parse(raw: String): PairingInfo {
        require(raw.length <= 512) { "토마데스크 연결 QR이 아닙니다." }
        val uri=try { URI(raw) } catch (_: Exception) {
            throw IllegalArgumentException("토마데스크 연결 QR이 아닙니다.")
        }
        require(uri.scheme == "tomadesk" && uri.host == "pair" &&
            uri.userInfo == null && uri.rawPath.isNullOrEmpty() && uri.rawFragment == null) {
            "토마데스크 연결 QR이 아닙니다."
        }
        val query=uri.rawQuery ?: throw IllegalArgumentException("PC 연결 주소가 없습니다.")
        val values=query.split('&').associate {
            val part=it.split('=',limit=2)
            require(part.size==2) { "PC 연결 주소가 올바르지 않습니다." }
            java.net.URLDecoder.decode(part[0],"UTF-8") to java.net.URLDecoder.decode(part[1],"UTF-8")
        }
        require(values.size==1 && values.containsKey("address")) { "PC 연결 주소가 올바르지 않습니다." }
        val address=try { URI(values.getValue("address")) } catch (_: Exception) {
            throw IllegalArgumentException("PC 연결 주소가 올바르지 않습니다.")
        }
        require(address.scheme=="http" && address.port==47831 && address.userInfo==null &&
            address.rawPath.isNullOrEmpty() && address.rawQuery==null && address.rawFragment==null &&
            address.toString()==values.getValue("address")) { "PC 연결 주소가 올바르지 않습니다." }
        val parts=(address.host ?: "").split('.')
        require(parts.size==4 && parts.all { it.isNotEmpty() && it.all(Char::isDigit) &&
            (it=="0" || !it.startsWith('0')) && (it.toIntOrNull()?.let { value -> value in 0..255 }==true) }) {
            "PC IPv4 주소가 올바르지 않습니다."
        }
        require(parts.joinToString(".")!="127.0.0.1" && parts[0]!="0" && parts[0]!="224") {
            "휴대폰에서 접근할 수 있는 PC 주소가 아닙니다."
        }
        return PairingInfo(values.getValue("address"))
    }
}
