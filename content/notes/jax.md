---
title: "JAX"
date: 2025-06-15T18:00:18+02:00
draft: false
---

Some collected useful things from writing JAX

### Environment variables for debugging

```bash
JAX_DEBUG_NANS=1
JAX_DIABLE_JIT=1
```

### Choosing gpus and platforms for JAX

(for CUDA in general)

```bash
CUDA_VISIBLE_DEVICES=3 # for gpu 3, 0-indexed
```

for JAX, if you don't want to use GPU memory for a simple job that still needs a JAX import

```
JAX_PLATFORMS=      # blank for default/all
JAX_PLATFORMS=cpu   # just cpu
```

If you want to use tensorflow-datasets without tensorflow also using gpu space, make sure to install `tensorflow-cpu` specifically.

