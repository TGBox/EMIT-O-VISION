\ EMIT-O-VISION - renders a grayscale video stream from stdin as ASCII art.
\
\ Stream protocol (written by bridge.py / Python runner):
\   Each frame begins with a 4-byte header:
\     width  (u16, little endian)
\     height (u16, little endian)
\   Followed by:
\     width*height bytes, one gray value 0..255 per pixel, row by row.
\   The stream repeats until stdin is closed (EOF).

\ Brightness ramp from dark to bright (first character is a space)
: charset ( -- c-addr u )  s"  .:-=+*#%@" ;

0 value width
0 value height
0 value frame-size
0 value cur-cap
0 value frame-buf
create stream-header 4 allot

\ --- ANSI terminal control ---------------------------------------------
: csi          ( -- )  27 emit [char] [ emit ;
: cursor-home  ( -- )  csi ." H" ;
: clear-screen ( -- )  csi ." 2J" ;
: hide-cursor  ( -- )  csi ." ?25l" ;
: show-cursor  ( -- )  csi ." ?25h" ;

\ --- Input ---------------------------------------------------------------
: u16le@ ( addr -- u )  dup c@  swap 1+ c@ 8 lshift  or ;

\ Reads exactly u bytes from stdin into addr; false on end of stream
: read-exactly ( addr u -- flag )
  begin dup 0> while
    2dup stdin read-file throw     ( addr u n )
    dup 0= if drop 2drop false exit then
    /string
  repeat
  2drop true ;

\ Ensures buffer has enough capacity for width*height
: ensure-frame-buf ( -- )
  width height * to frame-size
  frame-size cur-cap > if
    frame-buf if frame-buf free throw then
    frame-size allocate throw to frame-buf
    frame-size to cur-cap
  then ;

\ --- Rendering -----------------------------------------------------------
\ Maps a gray value 0..255 onto a character of the brightness ramp
: lum>char ( u8 -- char )  charset rot * 256 / + c@ ;

: pixel@ ( x y -- u8 )  width * + frame-buf + c@ ;

: render-frame ( -- )
  cursor-home
  height 0 ?do
    width 0 ?do  i j pixel@ lum>char emit  loop
    i height 1- < if cr then    \ no newline after last row: prevents terminal scrolling
  loop
  12 emit                       \ ASCII 12 (Form Feed) signals end of frame for pipes/files
  stdout flush-file throw ;

\ --- Main loop -----------------------------------------------------------
: run ( -- )
  clear-screen hide-cursor
  begin
    stream-header 4 read-exactly
  while
    stream-header u16le@ to width
    stream-header 2 + u16le@ to height
    width 0> height 0> and if
      ensure-frame-buf
      frame-buf frame-size read-exactly if
        render-frame
      else
        exit
      then
    else
      exit
    then
  repeat ;

\ catch handles Ctrl+C or IO errors gracefully so the cursor is always restored
' run catch drop
show-cursor cr
bye
