- Build the geometry with the first-class tools: sketches, `pad_sketch`,
  `pocket_sketch`, `pocket_through`, `pocket_blind`, `revolve_sketch`,
  `groove_sketch`, `sweep_sketch`, `fillet_edges`, `chamfer_edges`,
  `linear_pattern`, `polar_pattern`, `mirrored`, `create_primitive`, `boolean`.
  Use `execute_code` only to read state, to load a file, for an operation no
  tool offers (say which one), and for the finalize step. Do not script the
  whole part in one `execute_code` call: a part built in one step is looked at
  once, and every mistake in it is found late.
