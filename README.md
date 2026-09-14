# Plasticify

**Author:** keegang6705 - https://keegang.cc/ , DeepseekV4

Gives Minecraft a flat, glossy plastic finish.

## What it does

* Blocks and items are replaced with flat plastic versions of themselves, so
  everything in the world looks moulded rather than textured.
* Anything with real artwork in it - pumpkin faces, TNT, item icons, painted
  blocks - keeps its detail and only picks up the plastic shine.
* Mobs are left as they are, shine included, so faces and fur still read
  properly.
* Animations keep animating, at the same speed as vanilla.
* Material maps are included, so shaders light the surface as smooth, glossy
  plastic.

## Install

1. Copy the `Plasticify` folder into your `resourcepacks` folder.
2. In game, open Options -> Resource Packs and enable Plasticify.
3. Put it above any other pack whose textures you want it to replace.

## Requires

The gloss needs a shader with Advanced Materials enabled 
(Shader Options -> Material -> Advanced Materials) with a plain shader or
no shader, it still renders as flat plastic.

Material maps: `_n` is a flat normal, `_s` is roughness 0.03 with 7.8%
reflectivity.

## Left alone

Menus, fonts, maps, paintings, the sky and the colourmaps are not touched, so
nothing becomes hard to read.
