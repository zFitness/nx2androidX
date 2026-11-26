package com.nx.android.agent.runtime

import java.io.File
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder

/**
 * The material the App ships: it is planted on the device where the engine reads it, and a file
 * the player (or the assistant) has written for itself is left alone.
 *
 * The material is read out of the App's own assets folder: the very files that go into the
 * package, so the test and the product cannot drift apart.
 */
class AgentPlanterTest {

    @get:Rule
    val tmp = TemporaryFolder()

    /** The App's own assets: the material that goes into the package. */
    private val assets = File("src/main/assets/nx2a")

    private fun plant(root: File) =
        AgentPlanter(FileSeedSource(assets), root).plant()

    @Test
    fun `every piece of the material lands where the engine reads it`() {
        val root = tmp.newFolder("nx2a")

        plant(root)

        // the agreement: the engine loads its context file from the folder it starts in
        val agreement = File(root, "AGENTS.md")
        assertTrue("the agreement is in the working directory", agreement.isFile)
        assertTrue("the agreement says what it says", agreement.readText().contains("working agreement"))
        assertTrue("the agreement is ours", File(root, "AGENTS.md.seed").isFile)

        // the skill: the engine finds it in its own folder
        val skill = File(root, "agent/.agents/skills/card-unpack/SKILL.md")
        assertTrue("the skill is where the engine looks for it", skill.isFile)
        assertTrue("the skill names itself", skill.readText().contains("name: card-unpack"))

        // the agent definition: the engine reads it when it starts
        val definition = File(root, "agent/.pi/agent/agents/gamespec.md")
        assertTrue("the definition is where the engine looks for it", definition.isFile)
        assertTrue("the definition names its type", definition.readText().contains("name: gamespec"))

        // the knowledge we ship
        assertTrue(
            "the knowledge is in the workspace",
            File(root, "agent/workspace/knowledge/KNOWLEDGE.md").isFile,
        )
    }

    @Test
    fun `the faq the assistant answers from lands next to the knowledge`() {
        val root = tmp.newFolder("nx2a")

        plant(root)

        // the how-to answers: the assistant reads them, the help page shows them - one file
        for (language in listOf("zh", "en")) {
            val faq = File(root, "agent/workspace/knowledge/faq_$language.json")
            assertTrue("the faq ($language) is in the workspace", faq.isFile)
            assertTrue("the faq ($language) has questions in it", faq.readText().contains("\"q\""))
        }

        // the agreement says where they are: without that the assistant goes looking
        val agreement = File(root, "AGENTS.md").readText()
        assertTrue(
            "the agreement points at the faq",
            agreement.contains("agent/workspace/knowledge/faq_zh.json"),
        )
        assertTrue(
            "the agreement points at the faq",
            agreement.contains("agent/workspace/knowledge/faq_en.json"),
        )
    }

    @Test
    fun `the port failures skill and its references land with it`() {
        val root = tmp.newFolder("nx2a")

        plant(root)

        // the knowledge the case worker reads, with the documents it reads
        val skill = File(root, "agent/.agents/skills/port-failures/SKILL.md")
        assertTrue("the skill is where the engine looks for it", skill.isFile)
        assertTrue("the skill names itself", skill.readText().contains("name: port-failures"))
        for (reference in listOf("build-failures.md", "shader-split.md", "runtime-symptoms.md")) {
            val file = File(root, "agent/.agents/skills/port-failures/references/$reference")
            assertTrue("the reference $reference travels with the skill", file.isFile)
        }
        // the index the search reads, and the search itself
        assertTrue(
            "the case index travels with the skill",
            File(root, "agent/.agents/skills/port-failures/references/case-index.tsv").isFile,
        )
        // the search itself lives in the tool tree now (tools/memory_search.py), not in the
        // skill: the skill points at it
        assertTrue(
            "the skill points at the search",
            skill.readText().contains("tools/memory_search.py"),
        )
    }

    @Test
    fun `a skill the player wrote is left alone`() {
        val root = tmp.newFolder("nx2a")
        val skill = File(root, "agent/.agents/skills/card-unpack/SKILL.md")
        skill.parentFile.mkdirs()
        skill.writeText("我自己写的拆包步骤")

        plant(root)

        assertEquals("我自己写的拆包步骤", skill.readText())
    }

    @Test
    fun `the agreement the player wrote is left alone`() {
        val root = tmp.newFolder("nx2a")
        val agreement = File(root, "AGENTS.md")
        agreement.parentFile.mkdirs()
        agreement.writeText("我自己的规矩")

        plant(root)

        assertEquals("我自己的规矩", agreement.readText())
    }

    @Test
    fun `the material carries no language of its own`() {
        val root = tmp.newFolder("nx2a")

        plant(root)

        // 素材里没有语言：助手的回答语言跟玩家写的语言走
        val definition = File(root, "agent/.pi/agent/agents/gamespec.md").readText()
        assertTrue("the placeholder is gone", !definition.contains("{{player_language}}"))

        val agreement = File(root, "AGENTS.md").readText()
        assertTrue("the placeholder is gone", !agreement.contains("{{player_language}}"))
    }
}
