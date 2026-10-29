\ ====================================================================
\ Wolfenstein-Style 3D Echtzeit-Engine in reinem ANS Forth / Gforth
\ Features: Schatzkisten zum Einsammeln, Score, Maze, Feuerball, Tueren
\ Steuerung: WASD = Bewegen | F = Feuer | SPACE = Tuer | R = Map | Q = Ende
\ ====================================================================

80 constant W
24 constant H
16384 constant TILE   \ Fixpunkt-Skalierung: 1 Tile = 2^14 Einheiten

\ --- 1. Zufallsgenerator & Fixpunkt-Trigonometrie ---
utime drop value seed
: rnd      ( -- u )       seed 1103515245 * 12345 + dup to seed 16 rshift 32767 and ;
: choose   ( n -- 0..n-1 ) rnd swap mod ;
: rand-odd ( -- 3..13 )   6 choose 1+ 2* 1+ ;

create sintab
    0 ,   25 ,   50 ,   74 ,   98 ,  121 ,  142 ,  162 ,
  181 ,  198 ,  213 ,  226 ,  237 ,  245 ,  251 ,  255 ,
  256 ,  255 ,  251 ,  245 ,  237 ,  226 ,  213 ,  198 ,
  181 ,  162 ,  142 ,  121 ,   98 ,   74 ,   50 ,   25 ,
    0 ,  -25 ,  -50 ,  -74 ,  -98 , -121 , -142 , -162 ,
 -181 , -198 , -213 , -226 , -237 , -245 , -251 , -255 ,
 -256 , -255 , -251 , -245 , -237 , -226 , -213 , -198 ,
 -181 , -162 , -142 , -121 ,  -98 ,  -74 ,  -50 ,  -25 ,
does> swap 63 and cells + @ ;

: isin ( angle -- sin*256 ) sintab ;
: icos ( angle -- cos*256 ) 16 + sintab ;

\ --- 2. Sprite-DSL & Welt-Speicher (5 = Schatzkiste) ---
: srow: ( "8chars" -- ) parse-name bounds ?do i c@ c, loop ;

create sprite-bmp
  srow: ..^..^..
  srow: .######.
  srow: #O####O#
  srow: ########
  srow: .#\--/#.
  srow: ..####..
  srow: .#.##.#.
  srow: #..##..#

create world 256 allot

: map-addr ( mx my -- addr ) 15 and 4 lshift swap 15 and + world + ;
: tile@    ( mx my -- id )   map-addr c@ ;
: tile!    ( id mx my -- )   map-addr c! ;
: solid?   ( mx my -- flag ) tile@ 1 4 within ; \ 1-3 fest, 4 t.offen, 5 schatz

\ --- 3. Prozeduraler Dungeon- & Schatz-Generator ---
: clear-world ( -- )  16 0 do 16 0 do 0 i j tile! loop loop ;
: carve-east  ( x y -- x y ) over 13 < if 2dup swap 1+ swap 0 -rot tile! then ;
: carve-south ( x y -- x y ) dup  13 < if 2dup 1+ 0 -rot tile! then ;
: carve-dir   ( x y -- x y ) over 13 = if carve-south exit then
                             dup  13 = if carve-east  exit then
                             2 choose if carve-east else carve-south then ;
: carve-cell  ( x y -- )   2dup 0 -rot tile! carve-dir 3 choose 0= if carve-east carve-south then 2drop ;

: ns-corr? ( x y -- f ) 2dup 1- solid? -rot 1+ solid? and ;
: ew-corr? ( x y -- f ) 2dup swap 1- swap solid? -rot swap 1+ swap solid? and ;
: choke?   ( x y -- f ) 2dup ns-corr? -rot ew-corr? xor ;

: decorate-cell ( x y -- )
  2dup tile@ 1 = if 3 choose 0= if 2 -rot tile! else 2drop then exit then
  2dup + 1 and 0= if 2drop exit then
  2dup choke? if
    4 choose 0= if 3 -rot tile! else 6 choose 0= if 5 -rot tile! else 2drop then then
  else 2drop then ;

\ --- 4. Spiel-Zustand, Gegner & Schatz-Kollektion ---
0 value px     0 value py     0 value pa
0 value ex     0 value ey     0 value ea
3 value ehp    0 value ehit   0 value kills
0 value score  0 value tick   0 value anim
0 value fx     0 value fy     0 value fvx
0 value fvy    0 value flife  0 value flash

: spawn-enemy ( -- )
  rand-odd TILE * TILE 2/ + to ex
  rand-odd TILE * TILE 2/ + to ey
  64 choose to ea  3 to ehp  0 to ehit ;

: gen-dungeon ( -- )
  clear-world
  14 1 do 14 1 do i j carve-cell 2 +loop 2 +loop
  13 2 do 13 2 do i j decorate-cell loop loop
  0 1 1 tile!  0 2 1 tile!  0 1 2 tile!
  TILE 3 * 2 / dup to px to py  8 to pa
  0 to flife  spawn-enemy ;

: check-treasure ( -- )
  px 14 rshift  py 14 rshift  2dup tile@ 5 = if
    0 -rot tile!  score 250 + to score
  else 2drop then ;

: try-move ( dx dy -- )
  py + dup 14 rshift px 14 rshift swap solid? 0= if to py else drop then
  px + dup 14 rshift py 14 rshift solid? 0= if to px else drop then
  check-treasure ;

: toggle-door ( -- )
  px pa icos 55 * + 14 rshift  py pa isin 55 * + 14 rshift
  map-addr dup c@ dup 3 5 within if 7 swap - swap c! else 2drop then ;

: fire-gun ( -- )
  flife if exit then
  px to fx  py to fy
  pa icos 22 * to fvx  pa isin 22 * to fvy
  28 to flife  3 to flash ;

: hit-enemy? ( -- flag )
  ehp 0>  fx ex - abs 10000 < and  fy ey - abs 10000 < and ;

: damage-enemy ( -- )
  0 to flife  5 to ehit  ehp 1- to ehp
  ehp 0= if kills 1+ to kills  score 500 + to score  spawn-enemy then ;

: update-fireball ( -- )
  flash if flash 1- to flash then
  flife 0= if exit then
  flife 1- to flife
  fx fvx + to fx  fy fvy + to fy
  fx 14 rshift  fy 14 rshift  solid? if 0 to flife exit then
  hit-enemy? if damage-enemy then ;

: move-enemy ( -- )
  ehit if ehit 1- to ehit then
  ex ea icos 4 * +  ey ea isin 4 * +
  over 14 rshift over 14 rshift solid? 0=
  if to ey to ex else 2drop 4 choose 1+ 16 * ea + 63 and to ea then ;

\ --- 5. Raycasting-Kern & Texturen ---
0 value rx     0 value ry     0 value vx     0 value vy
0 value side   0 value hit-tile
0 value tex-u  0 value wh     0 value wcol
create zbuf W cells allot

: ray-vx ( col -- vx ) 40 - pa isin * 60 / pa icos swap - ;
: ray-vy ( col -- vy ) 40 - pa icos * 60 / pa isin + ;
: check-hit ( -- f )   rx 14 rshift ry 14 rshift tile@ dup to hit-tile 1 4 within ;
: step-ray  ( -- f )   rx vx + to rx  0 to side  check-hit if true exit then
                       ry vy + to ry  1 to side  check-hit ;
: calc-u    ( -- u )   side if rx else ry then 10 rshift 15 and ;

: cast-ray ( col -- dist )
  dup ray-vx to vx  ray-vy to vy  px to rx  py to ry
  512 1 do step-ray if calc-u to tex-u i unloop exit then loop
  1 to hit-tile  0 to tex-u  512 ;

: brick-tex  ( v -- c ) dup 3 and 0= if drop [char] = exit then 2 rshift 1 and 4 * tex-u + 7 and 0= if [char] | exit then side if [char] + else [char] # then ;
: pillar-tex ( v -- c ) dup 2 < over 13 > or if drop [char] = exit then 5 11 within tex-u 5 11 within and if [char] @ exit then tex-u 1 and if [char] | else [char] : then ;
: door-tex   ( v -- c ) dup 2 < tex-u 2 < or tex-u 13 > or if drop [char] # exit then dup 8 = tex-u 12 = and if drop [char] O exit then 7 = if [char] = exit then tex-u 3 and 0= if [char] | else [char] : then ;
: wall-tex   ( v -- c ) hit-tile 1 = if brick-tex exit then hit-tile 2 = if pillar-tex exit then door-tex ;
: wall-color ( -- ansi ) hit-tile 1 = if 36 else hit-tile 2 = if 33 else 35 then then side 0= if 60 + then ;

\ --- 6. Framebuffer & 3D-Renderer ---
create fb W H * allot
create cb W H * allot
97 value pen

: plot  ( c col row -- ) W * +  pen over cb + c!  fb + c! ;
: row-v ( row -- v )     12 wh - - 8 * wh / 15 and ;

: draw-pixel ( col row -- )
  dup 12 wh - < if 90 to pen bl -rot plot exit then
  dup 12 wh + < if wcol to pen dup row-v wall-tex -rot plot exit then
  32 to pen dup 18 > if [char] : else [char] . then -rot plot ;

: draw-col ( col -- )
  dup cast-ray dup 768 swap / 1 max to wh  wall-color to wcol
  over cells zbuf + !
  H 0 do dup i draw-pixel loop drop ;

\ --- 7. 3D-Projektion (Sprite, Schatzkisten, Feuerball) ---
0 value sdist   0 value scol   0 value sh   0 value su

: project-pt ( wx wy -- valid? )
  py - swap px - swap
  over pa icos * over pa isin * + 16 rshift to sdist
  pa icos * swap pa isin * - 16 rshift
  sdist 6 400 within 0= if drop false exit then
  60 * sdist / 40 + to scol
  768 sdist / 16 min 1 max to sh  true ;

: sprite-char ( u v -- char )
  dup 5 > if swap anim xor swap then  7 and 3 lshift swap 7 and + sprite-bmp + c@ ;

: draw-srow ( col row -- )
  dup 0 H within 0= if 2drop exit then
  su over 12 sh - - 4 * sh / sprite-char
  dup [char] . = if drop 2drop exit then
  ehit if 93 else dup [char] O = over [char] ^ = or if 97 else 91 then then to pen  -rot plot ;

: draw-scol ( col -- )
  dup 0 W within 0= if drop exit then
  dup cells zbuf + @ sdist < if drop exit then
  dup scol sh - - 4 * sh / to su
  12 sh + 12 sh - ?do dup i draw-srow loop drop ;

: draw-sprite ( -- )
  ex ey project-pt 0= if exit then
  scol sh + scol sh - ?do i draw-scol loop ;

\ 3D-Schatzkisten Renderer
: draw-trow ( col row -- )
  dup 0 H within 0= if 2drop exit then
  93 to pen [char] $ -rot plot ;

: draw-tcol ( col -- )
  dup 0 W within 0= if drop exit then
  dup cells zbuf + @ sdist < if drop exit then
  12 sh + 12 sh - ?do dup i draw-trow loop drop ;

: draw-treasures ( -- )
  16 0 do 16 0 do
    i j tile@ 5 = if
      i TILE * TILE 2/ +  j TILE * TILE 2/ +  project-pt if
        sh 2/ 1 max to sh
        scol sh + scol sh - ?do i draw-tcol loop
      then
    then
  loop loop ;

: draw-fcol ( col -- )
  dup 0 W within 0= if drop exit then
  dup cells zbuf + @ sdist < if drop exit then
  12 sh + 12 sh - ?do
    i 0 H within if i 12 = over scol = or if 97 else 93 then to pen [char] * over i plot then
  loop drop ;

: draw-fireball ( -- )
  flife 0= if exit then
  fx fy project-pt 0= if exit then
  sh 2/ 1 max to sh
  scol sh + scol sh - ?do i draw-fcol loop ;

\ --- 8. HUD & Minimap ---
0 value gx   0 value gy
: gxy!  ( col row color -- ) to pen to gy to gx ;
: gtype ( addr u -- )
  bounds ?do i c@ dup bl <> if gx gy plot else drop then gx 1+ to gx loop ;

: draw-gun ( -- )
  flash if 36 18 93 gxy! s"  \ * / " gtype  36 19 91 gxy! s" --(@)--" gtype then
  36 20 flash if 96 else 37 then gxy! s"   |H|  " gtype
  36 21 37 gxy! s"  /|H|\ " gtype
  36 22 90 gxy! s" | | | |" gtype
  36 23 90 gxy! s" |_____|" gtype ;

: map-glyph ( id -- char color )
  dup 1 = if drop [char] # 37 exit then
  dup 2 = if drop [char] % 93 exit then
  dup 3 = if drop [char] D 95 exit then
  dup 4 = if drop [char] : 35 exit then
  5 =     if      [char] $ 93 exit then
  bl 90 ;

: draw-minimap ( -- )
  16 0 do 16 0 do i j tile@ map-glyph to pen i j plot loop loop
  flife if 93 to pen [char] * fx 14 rshift fy 14 rshift plot then
  91 to pen [char] M ex 14 rshift ey 14 rshift plot
  92 to pen [char] @ px 14 rshift py 14 rshift plot ;

\ --- 9. Loop & Renderer ---
0 value last-c
0 value last-k
: ansi-fg ( color -- ) dup last-c = if drop exit then dup to last-c 27 emit [char] [ emit 0 .r [char] m emit ;

: show-row ( row -- ) W * dup W + swap do cb i + c@ ansi-fg fb i + c@ emit loop cr ;
: show-fb  ( -- )
  0 to last-c  0 0 at-xy
  H 0 do i show-row loop
  97 ansi-fg
  ." [WASD] [F]Feuer [SP]Tuer [R]Neu [Q]End | HP:" ehp 0 .r
  ."  Kills:" kills 0 .r
  ."  Pos:(" px 14 rshift 0 .r [char] , emit py 14 rshift 0 .r [char] ) emit
  ."  A:" pa 0 .r
  last-k if ."  Taste:" last-k emit then
  cr
  ." __W3D_STATS__ px=" px 0 .r ."  py=" py 0 .r ."  pa=" pa 0 .r ."  k=" last-k 0 .r
  12 emit stdout flush-file drop ;

: render ( -- )
  W 0 do i draw-col loop
  draw-treasures draw-sprite draw-fireball draw-gun draw-minimap show-fb ;

: handle-key ( char -- exit? )
  dup to last-k
  32 or case
    [char] w of pa icos  12 * pa isin  12 * try-move false endof
    [char] s of pa icos -12 * pa isin -12 * try-move false endof
    [char] a of pa 2 - 63 and to pa false endof
    [char] d of pa 2 + 63 and to pa false endof
    [char] f of fire-gun false endof
    [char] r of gen-dungeon false endof
    bl       of toggle-door false endof
    [char] q of true endof
    false swap
  endcase ;

: update-world ( -- ) tick 1+ dup to tick  2 rshift 1 and to anim  move-enemy update-fireball ;
: cursor-vis  ( flag -- ) 27 emit ." [?25" if [char] h else [char] l then emit ;

: main ( -- )
  gen-dungeon page false cursor-vis
  begin
    render update-world 30 ms
    key? if key handle-key else false then
  until
  true cursor-vis 0 ansi-fg page ;

main bye