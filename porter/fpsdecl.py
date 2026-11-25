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
# takes a cntpct_el0 delta in x0 and returns nanoseconds; reading cntfrq_el0 makes the conversion
# right on every device, not just the Switch's 19.2 MHz timer. The other routine blocks console
# auto-sleep; Android has no such service, so its whole rule is a no-op return.
BUILTINS = {
    'convertTickToTimeSpan': [
        ['mrs', 'x9', 'cntfrq_el0'],
        ['ucvtf', 'd0', 'x0'],
        ['ucvtf', 'd1', 'x9'],
        ['fdiv', 'd0', 'd0', 'd1'],
        ['movz', 'x9', 0xca00],
        ['movk', 'x9', 0x3b9a, 16],   # 1,000,000,000 is not a single logical immediate
        ['ucvtf', 'd2', 'x9'],
        ['fmul', 'd0', 'd0', 'd2'],
        ['fcvtzu', 'x0', 'd0'],
        ['ret'],
    ],
    'setUserInactivityDetectionTimeExtended': [['ret']],
}


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


def _token(x, ctx, mem=False):
    if isinstance(x, list): return '[' + ', '.join(_token(i, ctx, True) for i in x) + ']'
    if isinstance(x, str):
        if x.startswith('$'):
            n = x[1:]
            if n in ctx.vars: return ':lo12:v_' + n if mem else 'v_' + n
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
        if x[:1] in '+-' and x[1:].isdigit() and (ctx.mnem in ('b', 'bl', 'cbz', 'cbnz', 'tbz', 'tbnz') or ctx.mnem.startswith('b.')):
            return '. %s %s' % (x[0], x[1:])   # a signed branch immediate is PC-relative, not an address
        return x                              # register, mnemonic, condition
    if isinstance(x, bool): raise Refused(f'{x!r} is not an instruction operand')
    if isinstance(x, (int, float)):
        n = int(x) if isinstance(x, float) and x.is_integer() else x
        if ctx.mnem == 'movk' and n in (0, 16, 32, 48): return 'lsl #%d' % n   # movk's rotate syntax
        if ctx.mnem in ('fcmp', 'fcmpe') and n == 0: return '#0.0'   # GAS spells the float-zero immediate this way
        return str(n) if mem or ctx.mnem in ('adrp', 'adr', 'b', 'bl', 'blr', 'br') or ctx.mnem.startswith('b.') else '#%s' % n
    raise Refused(f'instruction operand {x!r}')


class Context:
    def __init__(self, y, image, vars_, consts, codes, text_range=None):
        self.vars, self.consts, self.codes = vars_, consts, codes
        self.image = image
        self.text_range = text_range
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

    def lines(self, ins, fold=True):
        # The usual `$var` load is adrp reg,$var / ldr out,[reg,$var]. A PC-relative literal load
        # does the same job in one instruction, needs no page arithmetic and is shorter in a cave.
        folded = list(ins) if not fold else []
        i = 0
        while fold and i < len(ins):
            a, b = ins[i], ins[i + 1] if i + 1 < len(ins) else None
            if (isinstance(a, list) and len(a) == 3 and a[0] == 'adrp' and str(a[2]).startswith('$')
                    and isinstance(b, list) and len(b) == 3 and b[0] == 'ldr' and isinstance(b[2], list)
                    and len(b[2]) == 2 and b[2][0] == a[1] and str(b[2][1]) == str(a[2])):
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
        return out

    def _sites(self, cave):
        cave_lines = []
        for n, (kind, vals) in self.vars.items():
            cave_lines.append('v_%s:' % n)
            if kind == 'double':
                cave_lines.append('\t.quad 0x%016X' % struct.unpack('<Q', struct.pack('<d', vals[60]))[0])
            else:
                cave_lines.append('\t.word 0x%08X' % struct.unpack('<I', struct.pack('<f', vals[60]))[0])
        for n, ins in self.codes.items():
            cave_lines.append('c_%s:' % n)
            cave_lines.extend(self.lines(ins))
        sites = [(cave, cave_lines)]
        sites.extend((off, self.lines(ins, False)) for off, ins, _ in self.masters)
        return sites

    def _build(self):
        try:
            measure = fpsasm.assemble(self._sites(0x100))
        except fpsasm.AsmError as e:
            raise Refused(f'the declarations do not assemble: {e}') from None
        need = len(measure[0x100])
        off = fpsasm.cave(self.image, need, forbidden=[o for o, _, _ in self.masters], text=self.text_range)
        try:
            final = fpsasm.assemble(self._sites(off))
        except fpsasm.AsmError as e:
            raise Refused(f'the declarations do not assemble at main+{off:#x}: {e}') from None
        cave_bytes = final[off]
        old = self.image[off:off + need]
        if old != cave_bytes:
            self.cuts.append((off, old.hex(), cave_bytes.hex(), 'FPSLocker-Warehouse declarations (variables and routines)'))
        at = off
        for n, (kind, _) in self.vars.items():   # variables come first, one word (or a double) each
            self.var_addr[n] = at
            at += 8 if kind == 'double' else 4
        for o, _, why in self.masters:
            new = final[o]
            old = self.image[o:o + len(new)]
            if old != new: self.cuts.append((o, old.hex(), new.hex(), why))
        self.notes.append('%d declared variable(s) and %d routine(s) assembled at main+%#x; %d instruction patch(es)' %
                          (len(self.vars), len(self.codes), off, len(self.masters)))

    def addr(self, a, what):
        """A config address: [VARIABLE, name] is the declared cell in main's image."""
        if isinstance(a, list) and len(a) == 2 and a[0] == 'VARIABLE':
            n = a[1]
            if n not in self.vars or self.var_addr.get(n) is None:
                raise Refused(f'{what}: undefined or unplaced variable {n!r}')
            return ['MAIN', self.var_addr[n]]
        return a


def build(y, image, text_range=None):
    """The context a config needs; no declarations and no instruction patches need no assembler."""
    vars_, consts, codes = declarations(y)
    _add_builtins(codes, y)
    return Context(y, image, vars_, consts, codes, text_range=text_range)
