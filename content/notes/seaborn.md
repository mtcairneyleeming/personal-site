---
title: "Plotting with Seaborn"
date: 2025-06-15T18:09:14+02:00
draft: false
---

I find `seaborn.objects` much more pleasant to use that matplotlib or the default Seaborn interface. Therefore, some useful references:


- [Tutorial](https://seaborn.pydata.org/tutorial/objects_interface.html) 
- [API reference](https://seaborn.pydata.org/api.html)

Extensions I've found:
- [Rolling sums](https://github.com/mwaskom/seaborn/issues/3300)
- [Seaborn objects recipes](https://github.com/Ofosu-Osei/seaborn_objects_recipes)


Questions I have:
- how to take an average (like `so.Agg()`) over both x and y axes, and over specific columns? e.g. if I have multiple runs with different hyperparameters (columns C1,C2,C3) and different methods to compare (C4-...), how do I plot the maxima over C1-C3?
- how to mix faceting and pairing not in the obvious way? e.g. facet on `row="A"` and 'pair' along the columns `y=["B","C"]`, so that we get 2 different y axes in the same row (but ideally shared across rows)
