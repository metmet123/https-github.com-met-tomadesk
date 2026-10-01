package com.toma.companion

import org.junit.Assert.assertEquals
import org.junit.Assert.assertThrows
import org.junit.Test

class PairingTest {
    private fun code(address: String) = "tomadesk://pair?address=${java.net.URLEncoder.encode(address,"UTF-8")}"

    @Test fun acceptsPcAddressFromAppLink() {
        assertEquals(PairingInfo("http://100.84.171.16:47831"),
            Pairing.parse(code("http://100.84.171.16:47831")))
    }

    @Test fun rejectsUntrustedQrAndAddresses() {
        for (value in listOf("http://100.84.171.16:47831", "tomadesk://other?address=http%3A%2F%2F100.84.171.16%3A47831",
            code("https://100.84.171.16:47831"), code("http://127.0.0.1:47831"),
            code("http://100.84.171.16:80"), code("http://100.84.171.16:47831/path"))) {
            assertThrows(IllegalArgumentException::class.java) { Pairing.parse(value) }
        }
    }
}
