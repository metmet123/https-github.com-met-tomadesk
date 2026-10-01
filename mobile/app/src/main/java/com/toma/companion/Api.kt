package com.toma.companion

import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL

class Api(private val address: String) {
    fun post(path: String, body: JSONObject): JSONObject {
        val url=URL(address.trimEnd('/')+path)
        require(url.protocol=="http" && url.userInfo==null && url.query==null) { "PC 연결 주소가 올바르지 않습니다." }
        val c=url.openConnection() as HttpURLConnection
        c.instanceFollowRedirects=false; c.connectTimeout=10000; c.readTimeout=60000
        c.requestMethod="POST"; c.doOutput=true; c.setRequestProperty("Content-Type","application/json")
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
