package com.toma.companion

import org.json.JSONObject
import java.net.URL
import java.security.MessageDigest
import java.security.SecureRandom
import java.security.cert.X509Certificate
import javax.net.ssl.*

class Api(private val address: String, fingerprint: String, private val token: String="") {
    private val pin=fingerprint.replace(":", "").replace(" ", "").uppercase()
    fun post(path: String, body: JSONObject): JSONObject {
        require(pin.matches(Regex("[0-9A-F]{64}"))) { "PC에 표시된 인증서 지문 64자리를 입력하세요." }
        val url=URL(address.trimEnd('/')+path)
        require(url.protocol=="https" && url.userInfo==null && url.query==null) { "HTTPS PC 주소를 입력하세요." }
        val context=SSLContext.getInstance("TLS")
        context.init(null,arrayOf<TrustManager>(object: X509TrustManager {
            override fun getAcceptedIssuers()=emptyArray<X509Certificate>()
            override fun checkClientTrusted(chain: Array<X509Certificate>, authType: String) { throw java.security.cert.CertificateException() }
            override fun checkServerTrusted(chain: Array<X509Certificate>, authType: String) {
                require(chain.isNotEmpty())
                chain[0].checkValidity()
                val actual=MessageDigest.getInstance("SHA-256").digest(chain[0].encoded).joinToString("") { "%02X".format(it.toInt() and 255) }
                if (!MessageDigest.isEqual(actual.toByteArray(),pin.toByteArray())) throw java.security.cert.CertificateException("PC 인증서 지문이 다릅니다.")
            }
        }),SecureRandom())
        val c=url.openConnection() as HttpsURLConnection
        c.sslSocketFactory=context.socketFactory
        // Certificate identity is the explicitly paired SHA-256 pin, not DNS.
        c.hostnameVerifier=HostnameVerifier { _, session ->
            val cert=session.peerCertificates.first() as X509Certificate
            val actual=MessageDigest.getInstance("SHA-256").digest(cert.encoded).joinToString("") { "%02X".format(it.toInt() and 255) }
            MessageDigest.isEqual(actual.toByteArray(),pin.toByteArray())
        }
        c.instanceFollowRedirects=false; c.connectTimeout=10000; c.readTimeout=60000
        c.requestMethod="POST"; c.doOutput=true; c.setRequestProperty("Content-Type","application/json")
        if(token.isNotEmpty()) c.setRequestProperty("Authorization","Bearer $token")
        try {
            val bytes=body.toString().toByteArray(Charsets.UTF_8); c.setFixedLengthStreamingMode(bytes.size)
            c.outputStream.use { it.write(bytes) }
            val status=c.responseCode
            val stream=if(status in 200..299) c.inputStream else c.errorStream
            val data=stream?.use { input ->
                val out=java.io.ByteArrayOutputStream(); val buffer=ByteArray(8192)
                while(true) { val n=input.read(buffer); if(n<0) break; require(out.size()+n<=64*1024*1024) { "자료가 너무 큽니다. PC에서 메모를 정리하세요." }; out.write(buffer,0,n) }
                out.toString("UTF-8")
            } ?: "{}"
            val result=JSONObject(data)
            if(status !in 200..299) throw IllegalStateException(result.optString("error","PC 연결 오류 ($status)"))
            return result
        } finally { c.disconnect() }
    }
}
