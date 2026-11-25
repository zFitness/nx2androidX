# DECLARATIONS and asm_a64 in FPSLocker-Warehouse configs (used by porter/fpslocker.py).
#
# A declaration is either a variable (a value the host writes to a cell in main), a const (an
# immediate used by the code), or a named routine. A MASTER_WRITE of type asm_a64 replaces machine
# instructions at a fixed main offset; its routine calls are `bl _name()`, and `$name` refers to a
# declared variable or const. The routines and variable cells are placed in free padding in main and
# assembled with the port's clang; the resulting bytes become CUTS of the rewriter.
import struct

from porter import fpsasm
from porter.fpslocker import Refused, TYPES, TARGETS, values


def _var_size(kind):
    """The cell width a declared variable needs in main: 64-bit types are two words."""
    return 8 if kind in ('int64', 'uint64', 'double') else 4


def number(v):
    """YAML numbers and hex strings (FPSLocker writes 0x3d088889 as a string sometimes)."""
    if isinstance(v, bool) or v is None: raise Refused(f'{v!r} is not a number')
    if isinstance(v, (int, float)): return v
    s = str(v).strip()
    try: return int(s, 0)
    except ValueError:
        try: return float(s)
        except ValueError: raise Refused(f'{v!r} is not a number') from None


# FORMAT.md's two built-in routines, callable from any B/BL in a config. convertTickToTimeSpan
# takes a cntpct_el0 delta in x0 and returns nanoseconds. The Switch's arch timer runs at 19.2
# MHz, so ns = ticks * 1e9 / 19.2e6 = ticks * 625 / 12. Do not read cntfrq_el0 here: Android traps
# that system register at EL0 (SIGILL at the first cave instruction on the Odin 3). The other
# routine blocks console auto-sleep; Android has no such service, so its rule is a no-op return.
BUILTINS = {
    'convertTickToTimeSpan': [
        ['mov', 'x9', 625],
        ['mul', 'x9', 'x0', 'x9'],
        ['mov', 'x10', 12],
        ['udiv', 'x0', 'x9', 'x10'],
        ['ret'],
    ],
    'setUserInactivityDetectionTimeExtended': [['ret']],
}


def _reg_occurs(x, reg):
    """Does a register appear anywhere in an instruction (including inside [base, ...])?"""
    if isinstance(x, str): return x == reg
    if isinstance(x, list): return any(_reg_occurs(i, reg) for i in x)
    return False


def _calls(x):
    if isinstance(x, str) and x.startswith('_') and x.endswith('()'):
        yield x[1:-2]
    elif isinstance(x, list):
        for i in x:
            yield from _calls(i)


def _add_builtins(codes, y):
    """Pull the built-in routines a config calls into its code cave before it is laid out."""
    todo = [[e.get('instructions') for e in (y.get(k) or []) if isinstance(e, dict)]
            for k in ('DECLARATIONS', 'MASTER_WRITE', 'unsafeCheck')]
    pending = [ins for group in todo for ins in group]
    while pending:
        for name in _calls(pending.pop()):
            if name not in codes and name in BUILTINS:
                codes[name] = BUILTINS[name]
                pending.append(BUILTINS[name])


def declarations(y):
    """(variables, constants, routines) of a config. variables: name → (type, {30: v, 60: v})."""
    vars_, consts, codes = {}, {}, {}
    for e in y.get('DECLARATIONS') or []:
        if not isinstance(e, dict): raise Refused(f'DECLARATIONS entry {e!r} is not a mapping')
        t = e.get('type')
        name = e.get('name')
        if not isinstance(name, str) or not name.isidentifier(): raise Refused(f'declaration name {name!r}')
        if t == 'variable':
            kind = e.get('value_type')
            if kind not in TYPES: raise Refused(f'variable {name}: value type {kind!r}')
            expr = e.get('evaluate', e.get('default_value'))
            if expr is None: raise Refused(f'variable {name} has no value')
            vars_[name] = (kind, {tg: values(expr, kind, tg, 'evaluate' in e)[0] for tg in TARGETS})
        elif t == 'const':
            consts[name] = number(e.get('value'))
        elif t == 'code':
            ins = e.get('instructions')
            if not isinstance(ins, list): raise Refused(f'routine {name} has no instruction list')
            codes[name] = ins
        else:
            raise Refused(f'declaration type {t!r} is not supported')
    return vars_, consts, codes


def _relative(ctx, addr):
    """Encode an absolute main offset for GAS.

    In a relocatable object the linker never applies relocations: GAS treats a bare number in
    adrp/adr/b/... as a DELTA from the current instruction, not an absolute address (a label only
    works when it is in the same page; adrp across pages assembles with a zero offset). Emit the
    PC-relative delta explicitly so the bytes are correct before we extract .text by hand.
    """
    pc = getattr(ctx, 'pc', 0)
    if ctx.mnem == 'adrp': return hex((int(addr) & ~0xfff) - (pc & ~0xfff))
    return hex(int(addr) - pc)   # adr, b, bl, cbz, ...: a byte delta from this instruction


def _token(x, ctx, mem=False):
    if isinstance(x, list): return '[' + ', '.join(_token(i, ctx, True) for i in x) + ']'
    if isinstance(x, str):
        if x.startswith('$'):
            n = x[1:]
            if n in ctx.vars:
                addr = (getattr(ctx, '_pass_addr', None) or {}).get(n)
                if addr is not None:
                    if ctx.mnem in ('adrp', 'adr', 'b', 'bl', 'blr', 'br') or ctx.mnem.startswith('b.'):
                        return _relative(ctx, addr)
                    if mem: return hex(addr & 0xfff)
                    return hex(addr)
                return ':lo12:v_' + n if mem else 'v_' + n
            if n in ctx.consts:
                v = ctx.consts[n]
                if ctx.mnem == 'mov': v &= 0xffff
                elif ctx.mnem == 'movk': v = (int(v) >> (ctx.shift or 0)) & 0xffff
                return '#%s' % (hex(int(v)) if isinstance(v, float) and v.is_integer() else v)
            raise Refused(f'undefined declaration ${n}')
        if x.startswith('_') and x.endswith('()'):
            n = x[1:-2]
            if n not in ctx.codes: raise Refused(f'undefined routine _{n}()')
            return 'c_' + n
        if x.startswith(':'): return x[1:]     # a branch label, defined or referenced
        # Android traps the physical counter at EL0; the virtual counter is the EL0-readable
        # arch timer (the kernel's own vDSO uses it). Both run at the SoC's arch-timer rate.
        if ctx.mnem == 'mrs' and x == 'cntpct_el0': return 'cntvct_el0'
        if x[:1] in '+-' and x[1:].isdigit() and (ctx.mnem in ('b', 'bl', 'cbz', 'cbnz', 'tbz', 'tbnz') or ctx.mnem.startswith('b.')):
            return '. %s %s' % (x[0], x[1:])   # a signed branch immediate is PC-relative, not an address
        return x                              # register, mnemonic, condition
    if isinstance(x, bool): raise Refused(f'{x!r} is not an instruction operand')
    if isinstance(x, (int, float)):
        n = int(x) if isinstance(x, float) and x.is_integer() else x
        if ctx.mnem == 'movk' and n in (0, 16, 32, 48): return 'lsl #%d' % n   # movk's rotate syntax
        if ctx.mnem in ('fcmp', 'fcmpe') and n == 0: return '#0.0'   # GAS spells the float-zero immediate this way
        if not mem and (ctx.mnem in ('adrp', 'adr', 'b', 'bl', 'blr', 'br') or ctx.mnem.startswith('b.')):
            return _relative(ctx, n)
        return str(n) if mem else '#%s' % n
    raise Refused(f'instruction operand {x!r}')


class Context:
    def __init__(self, y, image, vars_, consts, codes, text_range=None, data_range=None):
        self.vars, self.consts, self.codes = vars_, consts, codes
        self.image = image
        self.text_range = text_range
        self.data_range = data_range
        self.var_addr = {n: None for n in vars_}
        self.cuts, self.notes = [], []
        self.masters = []
        for i, e in enumerate(y.get('MASTER_WRITE') or []):
            if not isinstance(e, dict): raise Refused(f'MASTER_WRITE entry {i + 1} is not a mapping')
            if e.get('type') == 'asm_a64':
                off = e.get('main_offset')
                if not isinstance(off, int) or off < 0 or off + 4 > len(image):
                    raise Refused(f'MASTER_WRITE entry {i + 1}: bad main_offset {off!r}')
                ins = e.get('instructions')
                if not isinstance(ins, list): raise Refused(f'MASTER_WRITE entry {i + 1} has no instructions')
                self.masters.append((off, ins, f'FPSLocker-Warehouse MASTER_WRITE entry {i + 1}'))
            elif e.get('type') != 'bytes':
                raise Refused(f'MASTER_WRITE entry {i + 1}: type {e.get("type")!r} is not supported')
        if not (vars_ or codes or self.masters): return
        self._build()

    def lines(self, ins, fold=True, at=None):
        # The usual `$var` load is adrp reg,$var / ldr out,[reg,$var]. A PC-relative literal load
        # does the same job in one instruction, needs no page arithmetic and is shorter in a cave.
        if at is not None: self.pc = at
        folded = list(ins) if not fold else []
        i = 0
        while fold and i < len(ins):
            a, b = ins[i], ins[i + 1] if i + 1 < len(ins) else None
            if (isinstance(a, list) and len(a) == 3 and a[0] == 'adrp' and str(a[2]).startswith('$')
                    and isinstance(b, list) and len(b) == 3 and b[0] == 'ldr' and isinstance(b[2], list)
                    and len(b[2]) == 2 and b[2][0] == a[1] and str(b[2][1]) == str(a[2])
                    # The adrp also leaves the page base in a[1] for later instructions (e.g. a
                    # str to the same $var). Folding it away there would leave that base unset.
                    and not any(_reg_occurs(x, a[1]) for x in ins[i + 2:])):
                folded.append(['ldr', b[1], a[2]])
                i += 2
                continue
            folded.append(a)
            i += 1
        out = []
        for x in folded:
            if isinstance(x, str) and x.startswith(':'):
                out.append(x[1:] + ':')
                continue
            if not isinstance(x, list) or not x or not isinstance(x[0], str):
                raise Refused(f'instruction {x!r} is not [mnemonic, operands]')
            self.mnem, self.shift = x[0], None
            for o in x[1:]:
                if self.mnem == 'movk' and isinstance(o, int) and o in (0, 16, 32, 48): self.shift = o
            parts = []
            for o in x[1:]:
                if o == '!':   # the writeback flag belongs to the preceding memory operand
                    parts[-1] += '!' if parts else '!'
                else:
                    parts.append(_token(o, self))
            out.append('\t' + x[0] + (' ' + ', '.join(parts) if parts else ''))
            self.pc += 4
        return out

    def _var_base(self):
        """Where declared cells live. The loader seals text read-only+execute, so a routine's
        str to a variable in the code cave faults; data/bss stay writable. Put the cells at the
        tail of that range (past the game's last global) and keep only routines in the cave."""
        size = sum(_var_size(kind) for kind, _ in self.vars.values())
        if not self.data_range: return None, size   # no layout: cells share the cave (unit tests)
        lo, hi = self.data_range
        base = (hi - size) & ~7
        if base < lo or base + size > hi:
            raise Refused(f'declared variables do not fit in writable data main+{lo:#x}..{hi:#x}')
        return base, size

    def _sites(self, cave):
        self.base = cave
        self._pass_addr = {}
        vbase, vsize = self._var_base()
        at = cave if vbase is None else vbase
        var_lines = []
        for n, (kind, vals) in self.vars.items():
            self._pass_addr[n] = self.var_addr[n] = at
            var_lines.append('v_%s:' % n)
            if _var_size(kind) == 8:
                fmt = 'd' if kind == 'double' else TYPES[kind]
                v = float(vals[60]) if kind == 'double' else int(vals[60])
                var_lines.append('\t.quad 0x%016X' % struct.unpack('<Q', struct.pack('<' + fmt, v))[0])
                at += 8
            else:
                fmt = 'f' if kind == 'float' else TYPES[kind]
                v = float(vals[60]) if kind == 'float' else int(vals[60])
                var_lines.append('\t.word 0x%08X' % struct.unpack('<I', struct.pack('<' + fmt, v))[0])
                at += 4
        cave_lines = []
        at = at if vbase is None else cave
        for n, ins in self.codes.items():
            cave_lines.append('c_%s:' % n)
            # No folded literal loads: they need a relocation the raw .text does not carry.
            cave_lines.extend(self.lines(ins, False, at=at))
            at += 4 * sum(1 for i in ins if isinstance(i, list))
        sites = []
        if vbase is None:
            if var_lines or cave_lines: sites.append((cave, var_lines + cave_lines))
        else:
            if var_lines: sites.append((vbase, var_lines))
            if cave_lines: sites.append((cave, cave_lines))
        sites.extend((off, self.lines(ins, False, at=off)) for off, ins, _ in self.masters)
        return sites

    def _build(self):
        try:
            measure = fpsasm.assemble(self._sites(0x100))
        except fpsasm.AsmError as e:
            raise Refused(f'the declarations do not assemble: {e}') from None
        need = len(measure.get(0x100, b''))
        off = fpsasm.cave(self.image, need, forbidden=[o for o, _, _ in self.masters], text=self.text_range) if need else None
        try:
            final = fpsasm.assemble(self._sites(off if off is not None else 0x100))
        except fpsasm.AsmError as e:
            raise Refused(f'the declarations do not assemble at main+{off:#x}: {e}') from None
        vbase, vsize = self._var_base()
        if vbase is not None and self.vars:
            new = final[vbase]
            old = self.image[vbase:vbase + len(new)] or bytes(len(new))
            if old != new:
                self.cuts.append((vbase, old.hex(), new.hex(), 'FPSLocker-Warehouse declared variables (writable data)'))
        if off is not None:
            new = final[off]
            old = self.image[off:off + len(new)]
            if old != new:
                self.cuts.append((off, old.hex(), new.hex(), 'FPSLocker-Warehouse declarations (routines)'))
        for o, _, why in self.masters:
            new = final[o]
            old = self.image[o:o + len(new)]
            if old != new: self.cuts.append((o, old.hex(), new.hex(), why))
        where = f' at main+{off:#x}' if off is not None else ''
        vars_where = f' at main+{vbase:#x}' if self.vars and vbase is not None else ''
        self.notes.append('%d declared variable(s)%s, %d routine(s)%s; %d instruction patch(es)' %
                          (len(self.vars), vars_where, len(self.codes), where, len(self.masters)))

    def addr(self, a, what):
        """A config address: [VARIABLE, name] is the declared cell in main's image."""
        if isinstance(a, list) and len(a) == 2 and a[0] == 'VARIABLE':
            n = a[1]
            if n not in self.vars or self.var_addr.get(n) is None:
                raise Refused(f'{what}: undefined or unplaced variable {n!r}')
            return ['MAIN', self.var_addr[n]]
        return a


def build(y, image, text_range=None, data_range=None):
    """The context a config needs; no declarations and no instruction patches need no assembler."""
    vars_, consts, codes = declarations(y)
    _add_builtins(codes, y)
    return Context(y, image, vars_, consts, codes, text_range=text_range, data_range=data_range)
