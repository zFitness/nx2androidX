# Port checklist

The games the porter knows: every profile folder under `nxnative/dm/games/` is a row. A checked
row has the game's own `android.tsv` — the game is ported to Android (the keys are in
[ARCHITECTURE.md](ARCHITECTURE.md#game-profiles-on-android)). An unchecked row has the profile
only: `porter build <folder> --experimental` copies it into the build folder, writes an
experimental `android.tsv` and tries the build; the build may fail and the log says why
([UPSTREAM_PROFILES.md](UPSTREAM_PROFILES.md)).

Some games in the tree have an official Android release of their own, so there is nothing to
port here: Absolum, Balatro, Raging Loop. Their rows are the profiles upstream brought them up
with — the game is not missing on Android.

These have an official Android release too, and are ported here anyway: Unpacking.

**80 / 194 ported**

This file is generated: `python3 docs/gen_tables.py` reads the profiles and writes it. The facts
in a row are the profile's own — the name and the version from `game.tsv`, the status, the note
and the device the port was tested on from `android.tsv`.

**Credit.** A ported game names the person who brought it up (`ported by @handle`), taken from
the commit that added its profile. The ports from before this was written down are credited to
the author of the commit that introduced them.

- [x] 13 Sentinels: Aegis Rim · `01003FC01670C000` · playable · update 1.10 · 60 fps · ported by @shirai91
- [x] 13 Sentinels: Aegis Rim (Asia) · `01008D7016438000` · playable · base game 1.00 · 60 fps · the Asian release (Japanese, Korean, Chinese) · tested on the Xiaomi 23117RK66C (Android 16) · ported by @zfitness
- [ ] 13 Sentinels: Aegis Rim (Japan) · `010045C014650000` · 1.00
- [ ] Absolum · `0100A83022A22000` · 1.1.1
- [ ] Ace Attorney Investigations Collection · `010005501E68C000` · 1.0.0.2
- [x] Advance Wars 1+2: Re-Boot Camp · `0100300012F2A000` · playable · base game 1.0.0 · 60 fps (30 in battle on Switch) · ported by @shirai91
- [ ] AI: THE SOMNIUM FILES · `010089B00D09C000` · 1.0.1
- [ ] AI: THE SOMNIUM FILES - nirvanA Initiative · `0100713016CCC000` · 1.0.2
- [x] Animal Crossing: New Horizons · `01006F8002326000` · playable · update 3.0.3 · 30 fps (as on Switch) · local play over Wi-Fi with Switches that run ldn_mitm (Atmosphère 1.11.2 needs ldn_mitm 1.21.2) · ported by @shirai91
- [ ] ANIMAL WELL · `010020D01AD24000` · 1.0.10
- [x] Apollo Justice: Ace Attorney Trilogy · `010020D01B890000` · wip · v0 OnePlus 8 IN2010 (Snapdragon 865, Adreno 650) · ported by @armyja
- [ ] ASTRAL CHAIN · `01007300020FA000` · 1.0.1 · 60 fps
- [ ] Atelier Ryza: Ever Darkness & the Secret Hideout DX · `0100199023B2E000` · 1.2.0
- [ ] Balatro · `0100CD801CE5E000` · 1.1.3
- [ ] Bastion · `010038600B27E000` · 1.0.0
- [ ] Batman: Arkham Knight · `0100ACD0163D0000` · 1.0.5
- [ ] Bayonetta · `010076F0049A2000` · 1.1
- [ ] Bayonetta 2 · `01007960049A0000` · 1.2
- [ ] Bayonetta 3 · `01004A4010FEA000` · 1.2.0
- [ ] Big Brain Academy: Brain vs. Brain · `0100620012D6E000` · 1.2.0
- [x] Blasphemous 2 · `010040801A4C8000` · playable · update 1.0.8 · 60 fps · ported by @shirai91
- [ ] Brain Memory Training Academy · `0100F5D01DA3A000` · 1.0.0
- [ ] Burnout Paradise Remastered · `0100DBF01000A000` · 1.0.0
- [x] Captain Toad: Treasure Tracker · `01009BF0072D4000` · playable · update 1.4.2 · 60 fps · ported by @shirai91
- [x] Cardfight!! Vanguard Dear Days 2 · `0100B6F01DAF6000` · playable · update 1.7.2 · 30 fps, 60 with the 60 fps box · tested on the AYN Odin 2 with a Turnip driver · ported by @rospec14
- [x] Castlevania: Belmont's Curse · `0100BA4026E94000` · playable · update 1.1.0 · 60 fps · ported by @shirai91
- [x] Catherine: Full Body · `0100BC4010896000` · experimental · v0 Legion Y700 TB322FC (Snapdragon 8 Elite, Adreno 830, Android 16) · ported by @zFitness
- [ ] Catherine: Full Body · `0100BF00112C0000` · 1.0.1a
- [x] Celeste · `01002B30028F6000` · playable · update 1.4.1.1 · 60 fps · ported by @shirai91
- [ ] Chained Echoes · `0100C510166F0000` · 1.1.1
- [ ] Cult of the Lamb · `01002E7016C46000` · 1.5.28
- [ ] Cuphead · `0100A5C00D162000` · 1.3.7
- [x] Dark Souls: Remastered · `01004AB00A260000` · playable · update 1.0.3 · 30 fps · ported by @shirai91
- [ ] DAVE THE DIVER · `010097F018538000` · v1.0.6.1267
- [ ] Dead Cells · `0100646009FBE000` · 1.25.0
- [ ] Diablo II: Resurrected · `0100726014352000` · 1.0.34.0
- [ ] Diablo III: Eternal Collection · `01001B300B9BE000` · 2.7.7.92380
- [ ] Digimon Story Cyber Sleuth: Complete Edition · `010014E00DB56000` · 1.0.3
- [x] Disco Elysium - The Final Cut · `01006C5015E84000` · playable · base game 1.0.7 · 30 fps (as on Switch) · tested on the Sony XQ-DQ72 and the OnePlus 15 · ported by @C1oudust
- [x] Divinity: Original Sin 2 - Definitive Edition · `010027400CDC6000` · playable · v786432 Legion Y700 Gen 4 (Snapdragon 8 Elite, Adreno 830, Android 16) · ported by @shirai91
- [x] Donkey Kong Country Returns HD · `01009D901BC56000` · playable · update 1.1.0 · 60 fps · ported by @shirai91
- [ ] Donkey Kong Country: Tropical Freeze · `0100C1F0051B6000` · 1.0.2
- [ ] DOOM 3 · `010029D00E740000` · 1.0.5
- [ ] DRAGON BALL: Sparking! ZERO · `010035F022078000` · 2.0.76 · 60 fps
- [ ] DRAGON QUEST BUILDERS 2 · `010042000A986000` · 1.7.3d
- [ ] DRAGON QUEST I & II HD-2D Remake · `0100D7C01F254000` · 1.0.2 · 60 fps
- [ ] DRAGON QUEST III HD-2D Remake · `01003E601E324000` · 1.1.2 · 60 fps
- [ ] DRAGON QUEST VII Reimagined · `0100A9D01C446000` · 1.2.0 · 60 fps
- [ ] DRAGON QUEST XI S: Echoes of an Elusive Age – Definitive Edition · `01006C300E9F0000` · 1.0.4 · 60 fps
- [ ] EA SPORTS FC 27 · `0100C49025D3E000` · 1.8d.310c · 60 fps
- [x] FIFA 21 Legacy Edition · `01000A001171A000` · experimental · v0 Xiaomi 17 (Adreno 840, Android 17) · ported by @yidefu2012-cloud
- [x] Final Fantasy Resonance · `0100606026F12000` · playable · update 1.0.1 · 60 fps · Asian release: tested on the Legion Y700 TB321FU (Adreno 750) with a Turnip Vulkan driver · ported by @shirai91
- [x] FINAL FANTASY RESONANCE (Asian release) · `0100B8A026F14000` · playable · v65536 Lenovo Legion Y700 TB321FU (Snapdragon 8 Gen 3, Adreno 750, Android 16) · ported by @zFitness
- [x] FINAL FANTASY TACTICS - The Ivalice Chronicles · `010038B015560000` · experimental · ported by @intermission88
- [ ] FINAL FANTASY V · `0100AA201415C000` · 1.2.0_5
- [ ] FINAL FANTASY VI · `0100AA001415E000` · 1.2.1_5
- [ ] FINAL FANTASY X/X-2 HD Remaster · `0100BC300CB48000` · 1.0.0
- [ ] FINAL FANTASY XII THE ZODIAC AGE · `0100EB100AB42000` · 1.1.0
- [x] Fire Emblem Engage · `0100A6301214E000` · playable · update 2.0.0 · 60 fps (30 on Switch) · tested on the AYN Thor (Adreno 740) with a Turnip Vulkan driver; Qualcomm's own driver mis-draws Engage Attacks (#122) · ported by @intermission88
- [x] Fire Emblem: Three Houses · `010055D009F78000` · playable · v327680 Lenovo Legion Y700 TB322FC (Snapdragon 8 Elite, Adreno 830, Android 16) · ported by @shirai91
- [x] FM24 Touch · `01008B101B87A000` · playable · update 1.0.1 · 60 fps · OpenGL ES · touch or controller · ported by @shirai91
- [x] Football Manager 26 Touch · `0100D4A023450000` · playable · update 1.0.2 · 30 fps (as on Switch) · played by touch · port with a Turnip Vulkan driver (the crowd glitches on Qualcomm's driver) · ported by @shirai91
- [x] Graveyard Keeper 2 · `0100005027A18000` · playable · update 1.0.4 · 60 fps (30 on Switch) · ported by @shirai91
- [ ] Hades · `0100535012974000` · 1.0.38233
- [x] Hades II · `0100A00019DE0000` · playable · update 1.0 · 60 fps · ported by @shirai91
- [ ] Hollow Knight · `0100633007D48000` · 1.5.12620
- [x] Hollow Knight: Silksong · `010013C00E930000` · playable · update 1.0.30000 · 60 fps · ported by @shirai91
- [ ] Hyrule Warriors: Age of Calamity · `01002B00111A2000` · 1.3.0 · 60 fps
- [ ] Hyrule Warriors: Definitive Edition · `0100AE00096EA000` · 1.0.1
- [x] Kirby and the Forgotten Land · `01004D300C5AE000` · playable · update 1.1.0 · 30 fps (as on Switch) · tested on the AYN Thor (Adreno 740) with a Turnip Vulkan driver · ported by @DPR
- [ ] Kirby Star Allies · `01007E3006DDA000` · 4.0.0a
- [x] Kirby's Return to Dream Land Deluxe · `01006B601380E000` · playable · 60 fps · tested on the AYN Thor (Adreno 740) with a Turnip Vulkan driver · needs your console's firmware for its fonts (`--firmware`) · ported by @DPR
- [x] Layton's Mystery Journey: Katrielle and the Millionaires' Conspiracy DX+ · `0100FDB00AA80000` · playable · v65536 iQOO 9 V2171A (Snapdragon 8 Gen 1, Adreno 730, Android 15) · ported by @Bokyer
- [x] Lonely Mountains: Downhill · `0100A0C00E0DE000` · playable · base game 1.0.5 · 60 fps on Retroid Pocket 6 with PurpleVK · **work in progress**: brief transition glitch and occasional black/white flashes · ported by @alexsg91
- [ ] Luigi's Mansion 3 · `0100DCA0064A6000` · 1.4.0 · 60 fps
- [ ] Mario & Luigi: Brothership · `01006D0017F7A000` · 1.0.0 · 60 fps
- [ ] Mario + Rabbids Kingdom Battle · `010067300059A000` · 1.9.589692
- [ ] Mario + Rabbids® Sparks of Hope · `0100317013770000` · 1.6.2225577
- [ ] Mario Golf: Super Rush · `0100C9C00E25C000` · 4.0.0
- [ ] Mario Kart 8 Deluxe · `0100152000022000` · 4.0.0
- [ ] Mario Party Superstars · `01006FE013472000` · 1.1.1
- [x] Mario vs. Donkey Kong · `0100B99019412000` · playable · update 1.0.1 · 60 fps · ported by @shirai91
- [x] Mega Man Battle Network Legacy Collection Vol. 1 · `010038E016264000` · playable · update 1.0.2 · 60 fps, held · tested on the AYN Odin 2 (Adreno 740) with a Turnip Vulkan driver (Qualcomm's driver crashes or runs at 30) · Battle Network 1, 2 and 3 played: saves, battles, maps, gallery · the launcher's menus draw fully from the second port with the device connected after a first run (it builds some shaders at run time) · ported by @rospec14
- [x] Mega Man Battle Network Legacy Collection Vol. 2 · `0100734016266000` · playable · update 1.0.3 · 60 fps, held · tested on the AYN Odin 2 (Adreno 740) with a Turnip Vulkan driver · Battle Network 4, 5 and 6 played: saving, loading, battles, gallery · the launcher's menus draw fully from the second port with the device connected after a first run (it builds some shaders at run time) · ported by @rospec14
- [ ] Mega Man Legacy Collection · `01002D4007AE0000` · 1.0.3
- [ ] Metro 2033 Redux · `0100D4900E82C000` · 1.0.0
- [x] Metroid Dread · `010093801237C000` · playable · update 2.1.0 · 60 fps · ported by @shirai91
- [ ] Metroid Prime 4: Beyond · `010019A01E2F2000` · 1.1.0
- [ ] Metroid Prime Remastered · `010012101468C000` · 1.0.0
- [ ] Minecraft Dungeons II · `0100A7C01B792000` · 1.1.3.0 · 60 fps
- [ ] Monster Hunter Rise · `0100B04011742000` · 16.0.2 · 60 fps
- [ ] Monster Train 2 · `010051701FB46000` · 1.1.1
- [ ] Need For Speed™ Hot Pursuit Remastered · `010029B0118E8000` · 1.0.3 · 60 fps
- [x] NEO: The World Ends with You · `010043B013C5C000` · playable · update 1.03 · ported by @shirai91
- [x] NieR:Automata The End of YoRHa Edition · `010056B015FE8000` · boots · v131072 Xiaomi POCO F5 23049PCD8G (Snapdragon 7+ Gen 2 SM7475, Adreno 725, Android 15; Mesa Turnip v26 R8); Xiaomi Pad 7 2410CRP4CG (Snapdragon 7+ Gen 3 SM7675; Mesa Turnip v26 R8) · ported by @poweron0102
- [ ] NieR:Automata The End of YoRHa Edition · `0100B8E016F76000` · 1.0.3 · 60 fps
- [x] NOBUNAGA'S AMBITION: Shinsei · `01007AB012872000` · playable · v65536 Lenovo Legion Y700 TB321FU (Snapdragon 8 Gen 3, Adreno 750, Android 16) · ported by @mijuu
- [x] OCTOPATH TRAVELER · `010057D006492000` · boots · v327680 Red Magic Astra NP05J (Snapdragon 8 Elite, Adreno 830, Android 16) · ported by @sid350
- [x] OCTOPATH TRAVELER 0 · `01005270232F2000` · playable · update 1.0.5 · 60 fps · tested on the AYN Thor (Adreno 740) with a Turnip Vulkan driver · ported by @intermission88
- [x] OCTOPATH TRAVELER 0 (Chinese release) · `01001300232F4000` · playable · update 1.0.5 · 60 fps · the Chinese and Korean release · tested on the Xiaomi 23117RK66C (Android 16) · port with Game language: Chinese (Simplified) (`--language zh-Hans`) · ported by @zFitness
- [ ] OCTOPATH TRAVELER II · `0100A3501946E000` · 1.1.1 · 60 fps
- [ ] Ori and the Blind Forest: Definitive Edition · `010061D00DB74000` · 1.0.2
- [ ] Ori and the Will of the Wisps · `01008DD013200000` · 1.2.1
- [ ] Overcooked! All You Can Eat · `0100F28011892000` · 1.0.12 · 60 fps
- [x] Paper Mario: The Origami King · `0100A3900C3E2000` · playable · update 1.0.1 · 60 fps (30 on Switch) · ported by @shirai91
- [x] Paper Mario: The Thousand-Year Door · `0100ECD018EBE000` · wip · update 1.0.1 · 60 fps (30 on Switch) · **work in progress**: playable, but lighting flickers (walls go black for single frames after a fall) · ported by @shirai91
- [ ] Patrick's Parabox · `0100E44016C22000` · 1.0.1
- [ ] Persona 4 Golden · `010062B01525C000` · 1.0.2
- [ ] Persona 5 Royal · `01005CA01580E000` · 1.0.2
- [x] Picross S+ · `0100D7B01AE58000` · playable · update 1.0.1 · Retroid Pocket 6 / PurpleVK · menu and puzzle verified; **Mali rendering issues** · ported by @alexsg91
- [ ] Pikmin 4 · `0100B7C00933A000` · 1.1.1 · 60 fps
- [x] Pokémon Brilliant Diamond · `0100000011D90000` · playable · update 1.3.0 · 60 fps (30 on Switch) · tested on the AYN Thor (Adreno 740) with a Turnip Vulkan driver · ported by @intermission88
- [x] Pokémon Legends: Arceus · `01001F5010DFA000` · playable · update 1.1.1 · 30 fps (as on Switch) · tested on the AYN Thor (Adreno 740) with a Turnip Vulkan driver · ported by @shirai91
- [x] Pokémon Legends: Z-A · `0100F43008C44000` · playable · update 2.0.2 · 30 fps (as on Switch) · **tested to Lumiose station**: the city and battles not checked yet · ported by @shirai91
- [x] Pokémon Mystery Dungeon Rescue Team DX · `01003D200BAA2000` · playable · update 1.0.2 · 30 fps (as on Switch), 60 with the 60 fps option · tested on the AYN Odin 2 (Adreno 740) with a Turnip Vulkan driver · ported by @rospec14
- [x] Pokémon Scarlet · `0100A3D008C5C000` · experimental · update 4.0.0 · 50–60 fps (30 on Switch) · tested on the AYN Thor (Adreno 740) with a Turnip Vulkan driver · **work in progress**: tested in the opening and the South Province fields · ported by @minhoag
- [x] Pokémon Shield · `01008DB008C2C000` · playable · update 1.3.2 · 30 fps (as on Switch; 60 runs the game twice as fast) · tested on the AYN Odin 2 (Adreno 740) with a Turnip Vulkan driver · **tested to Postwick** and in wild battles · ported by @rospec14
- [x] Pokémon Sword · `0100ABF008968000` · playable · update 1.3.2 · 30 fps (as on Switch; 60 runs the game twice as fast) · tested on the AYN Odin 2 (Adreno 740) with a Turnip Vulkan driver · **tested to the Wild Area**, wild battles included; handheld mode draws blurred (docked is the default) · ported by @rospec14
- [x] Pokémon Violet · `01008F6008C5E000` · playable · 4.0.0 AYN Odin 2 (Adreno 740, Android 13, Turnip) · ported by @rospec14
- [ ] Portal · `01007BB017812000` · 1.0.3
- [ ] Portal 2 · `0100ABD01785C000` · 1.0.3
- [ ] Princess Peach: Showtime! · `01007A3009184000` · 1.0.0 · 60 fps
- [ ] Raging Loop · `010020400E1C2000` · 1.0.0
- [ ] Rayman Legends: Definitive Edition · `01005FF002E2A000` · 1.2
- [ ] Red Dead Redemption · `01007820196A6000` · 1.0.7 · 60 fps
- [ ] Return of the Obra Dinn · `010032E00E6E2000` · 1.0.1
- [x] Rhythm Heaven Groove · `0100D9F01D474000` · playable · base game 1.0.0 · 60 fps · tested on the Xiaomi 15 (Adreno 830) · ported by @Flying-dragon-boxing
- [ ] ROMANCE OF THE THREE KINGDOMS 8 REMAKE · `0100C2A01A730000` · 1.1.3
- [x] ROMANCE OF THE THREE KINGDOMS XIV · `0100CD4012DCA000` · playable · v786432 Xiaomi 2410DPN6CC haotian (Snapdragon 8 Elite, Adreno 830, Android 16) · ported by @shirai91
- [ ] ROMANCE OF THE THREE KINGDOMS XIV: Diplomacy and Strategy Expansion Pack · `0100ED7012DB2000` · 1.0.10
- [x] Rune Factory 3 Special · `0100E000191B4000` · experimental · ported by @rospec14
- [ ] SHIN MEGAMI TENSEI V: Vengeance · `010069C01AB82000` · 1.0.3 · 60 fps
- [ ] Sid Meier's Civilization VI · `010044500C182000` · 1.2.19
- [ ] Sid Meier's Civilization VII · `0100C3601518C000` · 1.5.0.1
- [x] Silver Pines · `0100D5B026844000` · playable · v65536 Xiaomi 23117RK66C (Redmi K70 Pro, Snapdragon 8 Gen 3, Adreno 750, Android 16) · ported by @zfitness
- [ ] Sonic Superstars · `01008F701C074000` · 1.1.8
- [x] South Park: The Stick of Truth · `010043600B6A6000` · playable · base game 1.0.0 · 30 fps · a Vulkan 1.3 driver is needed (Turnip packed on the Adreno 640) · ported by @Absenti
- [ ] SteamWorld Dig · `01009320084A4000` · 1.12.0
- [ ] SteamWorld Dig 2 · `0100CA9002322000` · 4.1.1
- [ ] SteamWorld Heist II · `010089C01E9CA000` · 1.5.1
- [ ] SteamWorld Heist: Ultimate Edition · `010016100A186000` · 2.2.1
- [ ] STEINS;GATE RE:BOOT · `01008BC024FDE000` · 1.0.3
- [ ] Streets of Rage 4 · `0100EC9010258000` · 1.0.9
- [ ] Subnautica · `0100429011144000` · 1.23.83358
- [ ] Subnautica: Below Zero · `010014C011146000` · 1.23.55063
- [ ] Super Mario 3D All-Stars · `010049900F546000` · 1.1.4
- [ ] Super Mario 3D All-Stars: Super Mario 64 · `010049900F546001` · 1.1.4
- [ ] Super Mario 3D All-Stars: Super Mario Sunshine · `010049900F546002` · 1.1.4
- [x] Super Mario 3D World + Bowser's Fury · `010028600EBDA000` · playable · update 1.2.2 · 60 fps · tested on the AYN Thor (Adreno 740) with a Turnip Vulkan driver · ported by @DPR
- [x] Super Mario Bros. Wonder · `010015100B514000` · playable · update 1.2.1 · 60 fps, dips to 40 · ported by @shirai91
- [ ] Super Mario Galaxy · `010099C022B96000` · 1.3.1
- [ ] Super Mario Galaxy 2 · `0100FD8022DAA000` · 1.4.0
- [x] Super Mario Odyssey · `0100000000010000` · playable · update 1.4.1 · 60 fps · shake the device to throw Cappy · ported by @shirai91
- [ ] Super Mario Party Jamboree · `0100965017338000` · 2.3.0
- [ ] Super Mario RPG · `0100BC0018138000` · 1.0.1
- [ ] Super Monkey Ball Banana Rumble · `010031F019294000` · 2.20
- [x] Super Robot Wars 30 · `0100ECB0129BE000` · playable · v655360 Lenovo Legion Y700 TB321FU (Snapdragon 8 Gen 3, Adreno 750, Android 16) · ported by @mijuu
- [ ] SUPER ROBOT WARS Y · `010063301BD50000` · 1.4.1
- [ ] Super Smash Bros. Ultimate · `01006A800016E000` · 13.0.5
- [ ] Taiko Risshiden V DX · `0100346017304000` · 1.1.1
- [x] Tales of Berseria Remastered · `01003FD01F22E000` · playable · v262144 (1.0.5) Sony XQ-DQ72 (Adreno 740) and OnePlus 15 (Snapdragon 8 Elite Gen 5) · ported by @C1oudust
- [x] Tales of Eternia Remastered · `010006E0230AC000` · playable · update 2.0.0 · 60 fps · ported by @shirai91
- [ ] Team Sonic Racing · `010092B0091D0000` · 1.0.3
- [x] Teenage Mutant Ninja Turtles: Shredder's Revenge · `0100BB8017F24000` · experimental · v1.0.9 Xiaomi 23117RK66C (Snapdragon 8 Gen 3, Adreno 750, Android 16)
- [ ] The Binding of Isaac: Rebirth · `01009BC00C38A000` · 1.0
- [ ] The Great Ace Attorney Chronicles · `010036E00FB20000` · 1.0.0
- [x] The Great Ace Attorney Chronicles · `0100D7F00FAAA000` · wip · v0 OPPO Pad OPD2101 (Snapdragon 870, Adreno 650, Android 15) · ported by @qzj112223
- [x] The Legend of Zelda: Breath of the Wild · `01007EF00011E000` · experimental · update 1.9.0 · 60 fps in the open world and shrines; about 30 in the busiest villages, which hold 60 while the phone is cool (30 on Switch) · the profile turns on `DM_GPU_TURBO=1` (the GPU at its highest clock: the phone runs hot, 67-76 °C; `DM_GPU_TURBO=0` in env.txt turns it off) · tested on the Galaxy S25 Ultra (Adreno 830) with Turnip (Stable Turnip v2, Mesa 26.2.3) · **work in progress**: tested on the Great Plateau, in shrines, villages and teleports · ported by @StepwiseCord804
- [x] The Legend of Zelda: Echoes of Wisdom · `01008CF01BAAC000` · playable · version 1.1.0 · playable on Retroid Pocket 6 with PurpleVK · **work in progress**: minor transparency artifacts around rifts · ported by @alexsg91
- [x] The Legend of Zelda: Link's Awakening · `01006BB00C6F0000` · playable · update 1.1.0 · 60 fps (drops to 30 on slow frames by default; uncomment the two NOPs in `patches.py` to hold 60 on fast chips — may cause judder and slow-motion on older devices) · tested on the Lenovo TB323FU (Snapdragon 8 Elite Gen 5, Adreno 840) · needs your console's firmware for its fonts (`--firmware`): without them the game crashes at startup because the fallback font lacks `U+25A1` · a new area can hitch while it loads · ported by @flowkscai
- [ ] The Legend of Zelda: Skyward Sword HD · `01002DA013484000` · 1.0.1
- [x] The Legend of Zelda: Tears of the Kingdom · `0100F2C0115B6000` · experimental · update 1.4.3 · 30 fps, 60 in caves and shrines · smoothest with a Turnip Vulkan driver · **work in progress**: 60 fps in the open world · ported by @shirai91
- [ ] The Rogue Prince of Persia · `01008D9022462000` · 1.1.0 · 60 fps
- [x] The World Ends with You -Final Remix- · `0100C1500B82E000` · playable · base game 1.0.0 · 60 fps · played by touch · ported by @shirai91
- [x] Tomodachi Life: Living the Dream · `010051F0207B2000` · playable · update 1.0.4 · 60 fps · ported by @shirai91
- [ ] Trails in the Sky 2nd Chapter · `01007A2027548000` · 1.0.4
- [ ] TRIANGLE STRATEGY · `0100CC80140F8000` · 1.1.1 · 60 fps
- [ ] TUNIC · `0100DA801624E000` · 1.0.3 · 60 fps
- [x] Ultra Kaiju Monster Rancher · `01008E0019388000` · playable · update 1.0.1 · 30 fps (60 runs the game twice as fast) · tested on the AYN Odin 2 (Adreno 740) with a Turnip Vulkan driver · handheld 3D resolution by default, docked in the app menu · tested through the tutorials and battles · ported by @rospec14
- [x] UNDER NIGHT IN-BIRTH Exe:Late[cl-r] · `010038C00EC34000` · playable · update 1.0.3 · 60 fps · ported by @shirai91
- [x] UNDER NIGHT IN-BIRTH II Sys:Celes · `0100BD401D18A000` · playable · update 1.42 · 60 fps · ported by @shirai91
- [x] Unicorn Overlord · `010069401ADB8000` · boots · update 1.05 · 60 fps · **boots**: saving and a full battle not tested yet · ported by @shirai91
- [x] Unicorn Overlord (Asia) · `010054B01AD92000` · experimental · v262144 Lenovo Legion Y700 TB320FC (Snapdragon 8+ Gen 1, Adreno 730, Vulkan 1.1, Android 15) · ported by @shirai91
- [x] Unpacking · `0100701015846000` · playable · update 2.01 · 60 fps · played by touch · ported by @shirai91
- [x] Untitled Goose Game · `010082400BCC6000` · playable · update 1.1.2 · 60 fps · ported by @christianoguedes
- [x] Viractal: Will You Trust Your Party? · `0100FD501F95A000` · playable · update 1.4.5 · ported by @shirai91
- [ ] Warhammer Survivors · `0100CAA026246000` · 1.0.0
- [ ] Well Dweller · `0100217023F6C000` · 1.0.0
- [ ] Xenoblade Chronicles 2 · `0100E95004038000` · 2.1.0
- [x] Xenoblade Chronicles 3 · `010074F013262000` · wip · update 2.2.0 · 30 fps · **work in progress**: some effects and models don't draw yet · ported by @shirai91
- [ ] Xenoblade Chronicles X: Definitive Edition · `0100453019AA8000` · 1.0.1 · 60 fps
- [x] Xenoblade Chronicles: Definitive Edition · `0100FF500E34A000` · playable · update 2.0.0 · 30 fps · tested on the AYN Odin 2 with a Turnip driver · **tested to Colony 9**, the pause menu and saving: later maps not checked yet · the scene drops to 896x504 in heavy fights · rarely crashes at boot (restart) · ported by @rospec14
- [ ] Yoshi's Crafted World · `01006000040C2000` · 1.0.1
- [ ] ŌKAMI HD · `0100276009872000` · 1.0.0
