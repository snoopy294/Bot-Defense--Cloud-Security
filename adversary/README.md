# adversary/ — the attacker (Phase 4)

- `bot/` — the repurposed `pokemon-monitor` evasion engine, repointed at **our own** deployed drop
  app (never third-party retailers). Generates the "bot" traffic class.
- `legit_traffic_gen/` — simulates human shoppers to generate the "human" class.

Together they produce the labeled dataset the Phase 5 ML detector trains on. Built in Phase 4.
