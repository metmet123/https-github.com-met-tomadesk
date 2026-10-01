package com.toma.companion

data class BlockSpec(val text:String,val level:Int=0,val indent:Int=0)

object Markdown {
    fun parse(source:String):List<BlockSpec> {
        val result=mutableListOf<BlockSpec>()
        var fence=false; var details=0
        for(line in source.replace("\r\n","\n").lines()) {
            val trimmed=line.trimStart()
            if(trimmed.startsWith("```") || trimmed.startsWith("~~~")) { fence=!fence; result.add(BlockSpec(line,0,details)); continue }
            if(fence) { result.add(BlockSpec(line,0,details)); continue }
            if(trimmed=="<details>" || trimmed=="<details open>") { details++; continue }
            if(trimmed=="</details>") { details=(details-1).coerceAtLeast(0); continue }
            val summary=Regex("^<summary>(.*?)</summary>$").find(trimmed)
            if(summary!=null) { result.add(BlockSpec("▾ "+summary.groupValues[1],0,(details-1).coerceAtLeast(0))); continue }
            val heading=Regex("^(#{1,4}) +(.+)$").find(trimmed)
            val indent=(line.length-trimmed.length)/2+details
            val text=when {
                heading!=null -> heading.groupValues[2]
                trimmed.startsWith("- [ ] ") -> "☐ "+trimmed.drop(6)
                trimmed.startsWith("- [x] ",true) -> "☑ "+trimmed.drop(6)
                trimmed.startsWith("- ") || trimmed.startsWith("* ") -> "• "+trimmed.drop(2)
                else -> line.trimStart()
            }
            result.add(BlockSpec(text,heading?.groupValues?.get(1)?.length ?: 0,indent.coerceAtMost(12)))
        }
        require(result.size<=2000) { "한 번에 가져올 수 있는 블록은 2,000개입니다." }
        return result
    }
}
