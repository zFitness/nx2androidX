# Observation gates for the linux-host boot comparison (2026-11-27): the game's engine init dies at
# main+0x65a084 in the window between StartThread(0x1005) and CreateThread(0x1006), inside the first
# engine allocation. The gates sit on that allocation's call chain (both hosts run the identical guest
# image, so the same gates fire on both and the two logs diff line for line): the allocation call's
# arguments and result, the object constructor's entry, the heap-context lookup and CreateBlock.
# No CUTS: the good path stays bit-for-bit unchanged. The host side is host/hle_obstrace.c (DM_OBSTRACE).
OBS = {
  # Mario vs. Donkey Kong (0100B99019412000) update 1.0.1 (v65536) main:
  '43ae51ee9766867da5f1272ca0d3d8a6': [
    (0x3159e4, 1, '52804600', 'the engine alloc: x0 = 560 (size), x1 = the manager\'s block, x2 = 8 (alignment)'),
    (0x3159f0, 2, 'aa0003f6', 'the engine alloc returned: x0 = the new object (null on the linux host as of 2026-11-27)'),
    (0xecf300, 3, 'a9be7bfd', 'the object constructor: x0 = this, x1 = the manager\'s block'),
    (0xecf318, 4, '9101c260', 'after the constructor\'s first call: x0 = this+0x70, x19 = this'),
    (0x449428, 5, 'a9be7bfd', 'the heap-context lookup: x0 = the default context, returns the per-thread heap'),
    (0x4448c0, 6, '120000a5', 'CreateBlock: the arguments as the caller passed them'),
    (0xe851e4, 7, 'f9000260', 'CreateBlock returned: x0 = the block (stored at [x19] = the manager\'s block field)'),
    (0x44490c, 8, 'aa0003f3', 'CreateBlock: the heap-context lookup returned (x0; null -> the fail path)'),
    (0x444940, 9, '927df018', 'the context virtual returned: x0 = the raw size answer'),
    (0xe85190, 11, 'f8695919', 'the block-candidate loop: x25 = this candidate from the registry table'),
    # gate 10 was dropped: 0xe851e0 is the bl CreateBlock itself and cannot host a gate. The two paths
    # are told apart by gate 6 (the CreateBlock entry): gate 6 fired since the last gate 7 = the call ran
    # and its result is x0 at gate 7; gate 7 with x0=0 and no gate 6 since = the direct zero write (the
    # candidate table had no suitable block: the mov x0,xzr; b 0xe851e4 pairs).
  ],
}
