package com.toma.companion

import org.junit.Assert.assertEquals
import org.junit.Assert.assertThrows
import org.junit.Test

class PairingTest {
    private val pin = "A".repeat(64)
    private fun code(url: String, fingerprint: String = pin) = "TOMADESK-PAIR-V1\n$url\n$fingerprint"

    @Test fun acceptsPcAddressAndPin() {
        assertEquals(PairingInfo("https://100.84.171.16:47831", pin),
            Pairing.parse(code("https://100.84.171.16:47831")))
    }

    @Test fun rejectsUntrustedQrAndAddresses() {
        for (value in listOf("https://100.84.171.16:47831", "TOMADESK-PAIR-V2\nhttps://100.84.171.16:47831\n$pin",
            code("http://100.84.171.16:47831"), code("https://192.168.1.2:47831"),
            code("https://100.84.171.16:80"), code("https://100.84.171.16:47831/path"),
            code("https://100.84.171.16:47831", "test"))) {
            assertThrows(IllegalArgumentException::class.java) { Pairing.parse(value) }
        }
    }
}
