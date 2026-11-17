---
title: "3D Fractal Generator" 
date: 2020-09-01
author: ["Max Cairney-Leeming"]
description: "Generate 3D models of the evolution of (line-based) fractals with Lindenmayer systems, suitable for 3D printing."
summary: "Generate 3D models of the evolution of (line-based) fractals with Lindenmayer systems, suitable for 3D printing."
cover:
    image: "sierpinski.png"
    alt: "A Sierpinski triangle fractal"
    relative: true
showToc: false
disableAnchoredHeadings: false

---

---

During my 2020 summer internship with Dr. Tom Crawford on his YouTube channel [Tom Rocks Maths](https://tomrocksmaths.com/), I made two videos about fractals and 3D printing, aimed at students and the general public interested in maths.

To accompany them, I built [fractals.maxcl.co.uk](https://fractals.maxcl.co.uk): a website with interactive explanations of Lindenmayer systems (L-systems), which turn simple string-rewriting rules into line-based fractals. A Rust server then converts the successive iterations of a fractal into a single 3D-printable model, with meshes of millions of triangles. The code is [on GitHub](https://github.com/mtcairneyleeming/fractals).

The two videos are embedded below.

<iframe width="560" height="315" src="https://www.youtube.com/embed/yMgaobj3Edw" title="Tom Rocks Maths: fractals video 1" frameborder="0" allow="accelerometer; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share" allowfullscreen></iframe>

<iframe width="560" height="315" src="https://www.youtube.com/embed/J0LyZSgVKVc" title="Tom Rocks Maths: fractals video 2" frameborder="0" allow="accelerometer; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share" allowfullscreen></iframe>
