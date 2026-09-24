## mol load

Load a molecule from a file. Syntax: `mol load <type> <filename>`.
Supported types include `pdb`, `psf`, `dcd`, `xyz`, `mol2`. Returns the
new molecule's molid as an integer. Example: `mol load pdb 1ubq.pdb`.

## mol new

Like `mol load` but lets you supply additional options inline. Common
form: `mol new <filename> type <type> waitfor all`. The `waitfor all`
clause makes loading synchronous so subsequent commands see all frames.

## mol delete

Delete a molecule by molid. Syntax: `mol delete <molid>` or
`mol delete top` to delete the currently active one. Use `mol delete all`
to clear every loaded structure.

## mol representation

Stage a representation style for the next `mol addrep` call. Syntax:
`mol representation <style> [args...]`. Common styles:

- `NewCartoon <thickness> <resolution> <aspect>` — backbone cartoon
- `Licorice <bond_radius> <sphere_res> <bond_res>` — sticks-and-balls
- `VDW <radius_scale> <resolution>` — space-filling spheres
- `Surf <probe_radius>` — Connolly molecular surface
- `QuickSurf <radius> <density> <grid> <isovalue>` — fast surface

Note: `mol representation` only stages the rep — you must call
`mol addrep <molid>` afterwards to commit it.

Concrete examples:

    mol representation NewCartoon 0.3 12.0 4.5
    mol representation Licorice 0.3 12.0 12.0
    mol representation VDW 1.0 12.0
    mol representation Surf 1.4
    mol representation QuickSurf 1.0 0.5 1.0 1.0

## mol color

Set the coloring scheme for the next-staged representation. Syntax:
`mol color <method>`. Methods include `Name`, `Type`, `ResName`,
`ResID`, `Chain`, `Beta`, `Index`, `Structure`, `User`, `ColorID <n>`.

## mol selection

Set the atom-selection string for the next-staged representation.
Syntax: `mol selection "<selection-language>"`. The selection language
supports keywords like `protein`, `nucleic`, `water`, `resname LIG`,
`within 5 of resname LIG`, and boolean combinators (`and`, `or`, `not`).

## mol material

Set the material applied to the next-staged representation. Syntax:
`mol material <name>`. Built-in materials: `Opaque`, `Transparent`,
`Ghost`, `Glossy`, `AOChalky`, `AOEdgy`, `AOShiny`. AO* materials only
render correctly under `render TachyonInternal`.

## mol addrep

Commit a staged representation onto a molecule. Syntax:
`mol addrep <molid>`. Must be preceded by `mol representation`,
`mol color`, `mol selection`, and (optionally) `mol material`. Returns
the new representation's index.

## mol delrep

Remove a representation from a molecule. Syntax:
`mol delrep <repindex> <molid>`. To clear every rep, iterate from the
highest index downward.
