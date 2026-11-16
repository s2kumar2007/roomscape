# Round 2 Video Demonstration Script: Roomscape

**Title**: Roomscape Round 2: Obstacle-Aware Navigation & Semantic POI Exploration  
**Duration**: ~3 minutes 45 seconds  
**Target Audience**: Judges, Technical Evaluators, Industry Reviewers  

---

## Storyboard & Timestamped Breakdown

### [0:00 - 0:35] Scene Overview & Round 2 Introduction
* **Visual**: Camera spawns at the main entrance of the digital twin room. First-person view of the 3D Gaussian splat scene with the HUD, minimap, and hovering POI labels visible.
* **Audio / Voiceover**:
  > "Welcome to Round 2 of Roomscape, our submission for the Techfest IIT Bombay Namma Space Challenge. In Round 1, we reconstructed a metric-accurate 3D digital twin from a handheld phone video. Now in Round 2, we transform this static visual twin into an intelligent, interactive spatial computing environment. Today we are demonstrating three key pillars: semantic Points of Interest with wall-occlusion culling, fuzzy keyboard-first search, and real-time obstacle-aware A* path planning with automated walking."

---

### [0:35 - 1:20] Interactive POI Labels & Line-of-Sight Wall Occlusion
* **Visual**:
  1. Mouse rotates around the room. POI labels ("Main Entrance", "Primary Workstation", "Collaboration Whiteboard", "Coffee Corner") float cleanly above their 3D blue locator pins.
  2. Demonstrator walks toward the lounge partition wall. As the partition moves between the camera and the Coffee Corner POI, the "Coffee Corner" label smoothly disappears.
  3. Demonstrator steps back into the open hallway; the label immediately reappears.
* **Audio / Voiceover**:
  > "Notice how each POI features an interactive floating badge projected from 3D space directly into the DOM overlay. To prevent visual clutter and confusion, labels are capped and depth-filtered. More importantly, our custom line-of-sight raycaster traces against the raw blocked occupancy grid in real time. Notice how the Coffee Corner label vanishes when blocked by this partition wall, completely eliminating visual bleed-through. Clicking any label instantly designates it as our destination."

---

### [1:20 - 2:05] Fast Fuzzy Search Modal
* **Visual**:
  1. Demonstrator presses `/` on the keyboard. The pointer lock releases and a sleek search modal opens instantly.
  2. Demonstrator types `whitbord` (with an intentional typo). The ranking engine instantly matches "Collaboration Whiteboard" at distance $3.4\text{ m}$.
  3. Demonstrator uses `↓` and `↑` arrow keys to highlight the item and hits `Enter`.
* **Audio / Voiceover**:
  > "Finding locations in large venues must be effortless. By pressing slash, the search bar appears with full keyboard and touch support. Our search engine ranks matches using exact, prefix, token, alias, and fuzzy Levenshtein distance with typo tolerance up to two edits. Notice how typing 'whitbord' correctly identifies the Collaboration Whiteboard. Each result indicates the real-time walking distance from our current position. Pressing Enter locks in our target."

---

### [2:05 - 2:55] Obstacle-Aware A* Path Planning
* **Visual**:
  1. A luminous green path of instanced 3D discs appears on the floor, accompanied by an updated polyline on the bottom-right 2D minimap.
  2. Camera tilts down to show the path navigating around the workstation desk: it strictly hugs the safe boundary with zero diagonal corner cutting.
  3. Top HUD displays the active navigation status: target name, remaining distance in meters, and estimated time of arrival (ETA).
* **Audio / Voiceover**:
  > "Upon selection, our zero-allocation TypeScript A* engine computes the optimal route in less than one millisecond. The algorithm operates on an inflated grid where safety margins prevent clipping. Notice the strict no-corner-cutting rule: diagonal traversals are only permitted when both orthogonal neighbors are completely unobstructed. The raw grid path is smoothed using continuous line-of-sight raycasting, producing natural, direct trajectories that never cross obstacles. Simultaneously, the bottom-right minimap reflects the exact path."

---

### [2:55 - 3:30] Auto-Walk Assistance & Real-Time Rerouting
* **Visual**:
  1. Demonstrator clicks "🚶 Walk me there" in the navigation HUD.
  2. The avatar automatically traverses along the smoothed waypoints while respecting collision boundaries.
  3. Demonstrator presses 'D' to manually divert off-course. Once the avatar strays $> 1.5\text{ m}$ away, the path automatically recalculates from the new position.
  4. The avatar arrives within $0.6\text{ m}$ of the whiteboard. The HUD updates to "🎉 Arrived at Collaboration Whiteboard!".
* **Audio / Voiceover**:
  > "For hands-free guidance, users can click 'Walk me there'. The auto-walk controller utilizes the collision engine's sliding response, guaranteeing the player never leaves walkable bounds. If a user manually wanders more than 1.5 meters off the planned route, the navigator dynamically reroutes in real time. Upon arrival within 0.6 meters of the target, the navigation state cleanly completes with an arrival confirmation."

---

### [3:30 - 4:00] POI Dev Authoring Mode & Verification Suite
* **Visual**:
  1. Demonstrator reloads the page with `?edit=1`. A targeting ring appears on the floor.
  2. Moving over clear floor turns the ring green; pointing at a wall turns it red. Demonstrator taps 'E' to place a new POI, and clicks 'Export poi.json'.
  3. Screen transitions to terminal showing `python scripts/check_all.py` passing all 5 stages (pytest, vitest, tsc, npm build, Playwright e2e) with zero GPU requirement.
* **Audio / Voiceover**:
  > "Finally, adding new locations is seamless with our built-in dev mode (?edit=1). Authors can aim their crosshairs, verify walkable snapping in green, drop POIs with key 'E', and export a validated poi.json directly from their browser without any backend server. All of this is validated by an automated, cross-platform test pipeline with 100% green checks on standard CPU hardware. Thank you for exploring Roomscape Round 2!"
