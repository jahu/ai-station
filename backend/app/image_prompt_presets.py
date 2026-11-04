"""Frozen legacy Qwen styling, copied from the unchanged reference pipeline.

Only the managed adapter imports these constants; external scripts retain their
own version and prompt behavior. Instruction/prompt-only modes bypass them.
"""

PHOTO_SUFFIX = """
photorealistic RAW photograph,
natural realistic skin,
subtle visible skin pores,
natural skin imperfections,
fine facial detail,
realistic hair strands,
realistic eyes,
physically accurate natural lighting,
natural shadows,
realistic material textures,
DSLR photography,
50mm lens,
natural depth of field,
subtle realistic color grading
""".replace("\n", " ").strip()

IDENTITY_PREFIX = """
Preserve the exact identity of the person in the source image.
Do not change the person's face.
Preserve exact facial geometry and recognizable identity.
Preserve face shape, forehead, eyes, eye spacing, eyebrows,
nose shape, lips, mouth shape, jawline, chin, ears and skin tone.
Preserve hairstyle, hairline and apparent age.
Preserve natural skin texture and existing facial details.
Do not smooth, beautify, retouch, stylize or redesign the face or skin.
Preserve body proportions unless explicitly requested otherwise.
Preserve pose, camera angle, perspective and overall composition.
Do not unnecessarily modify any part of the image.
The result must clearly depict the exact same person.
Only perform the requested change:
""".replace("\n", " ").strip()

RECOMPOSE_PREFIX_SINGLE = """
Use the reference image as an identity reference for the main person.

Preserve the exact facial identity of the person.
Preserve recognizable face shape, eyes, eyebrows, nose, lips, jawline,
skin tone, hairstyle, hairline and apparent age.

Preserve the person's general physique, build, body proportions and overall silhouette.

You are allowed to freely redesign and change:
- pose
- body position
- clothing
- environment
- background
- camera angle
- framing
- lighting
- props
- other people
- activity
- scene composition

Do not preserve the original pose or background unless explicitly requested.
Create a completely new scene if needed, while keeping the same recognizable person.

Create this new scene:
""".replace("\n", " ").strip()

RECOMPOSE_PREFIX_MULTI = """
Use all provided reference images as identity references for the same main person.

Preserve the exact facial identity of that person.
Preserve recognizable face shape, eyes, eyebrows, nose, lips, jawline,
skin tone, hairstyle, hairline and apparent age.

Preserve the person's general physique, build, body proportions and overall silhouette.

Synthesize a coherent depiction of the same person using all reference images together.

You are allowed to freely redesign and change:
- pose
- body position
- clothing
- environment
- background
- camera angle
- framing
- lighting
- props
- other people
- activity
- scene composition

Do not preserve the original pose or background unless explicitly requested.
Create a completely new scene if needed, while keeping the same recognizable person.

Create this new scene:
""".replace("\n", " ").strip()
