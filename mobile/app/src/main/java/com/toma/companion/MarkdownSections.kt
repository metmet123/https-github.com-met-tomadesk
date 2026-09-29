package com.toma.companion

data class MarkdownSection(val level:Int,val heading:String,val body:String)

/** ATX headings outside fenced code; source itself is never rewritten. */
object MarkdownSections {
    fun split(source:String):List<MarkdownSection> {
        val result=mutableListOf<MarkdownSection>(); var level=0; var heading=""; val body=StringBuilder()
        var fence:Char?=null; var fenceLength=0
        fun flush() { if(heading.isNotEmpty() || body.isNotEmpty())result.add(MarkdownSection(level,heading,body.toString())); body.setLength(0) }
        for(line in source.replace("\r\n","\n").split("\n")) {
            val f=Regex("^ {0,3}(`{3,}|~{3,})(.*)$").find(line)
            if(f!=null) {
                val run=f.groupValues[1]
                if(fence==null) { fence=run[0]; fenceLength=run.length }
                else if(run[0]==fence && run.length>=fenceLength && f.groupValues[2].isBlank())fence=null
                body.append(line).append('\n'); continue
            }
            val h=if(fence==null)Regex("^ {0,3}(#{1,6})(?:[ \t]+(.*)|$)").find(line) else null
            if(h!=null) { flush();level=h.groupValues[1].length;heading=line }
            else body.append(line).append('\n')
        }
        flush(); return result
    }
}
