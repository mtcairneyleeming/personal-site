---
title: "Pandas and Jupyter Tips"
date: 2025-06-15T14:03:05+02:00
draft: false
---


### Automatic reloading for Jupyter

```python
%load_ext autoreload
%autoreload 2
```


### Setting Pandas display options
To avoid truncation of long DataFrames, you can set the following options:

```python
import pandas as pd
pd.set_option("display.expand_frame_repr", False)
pd.options.display.max_columns = None
pd.options.display.max_rows = None
```

### 
