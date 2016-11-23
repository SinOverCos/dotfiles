execute pathogen#infect()

set cm=blowfish2

" for tags
set tags=./.ctags;$HOME
set autochdir

syntax on
colorscheme railscasts
set background=dark

filetype plugin on

set number
"set relativenumber 

set noautoindent
set nocindent
set smartindent

set expandtab
set tabstop=4
set shiftwidth=4
set softtabstop=4

set statusline=%F%m%r%h%w\ [FORMAT=%{&ff}]\ [TYPE=%Y]\ [ASCII=\%03.3b]\ [HEX=\%02.2B]\ [LEN=%L]\ [POS=%04l,%04v][%p%%]
set laststatus=2

"let g:netrw_liststyle=3

set mouse=a
set backspace=indent,eol,start

set hlsearch
set ignorecase
set smartcase
set vb

" looking for next instance of word puts the next instance in the middle of
" the screen - pretty annoying if you want to see next instance relative to
" where the previous instance though
"nnoremap n nzz

" clear highlight from search
nnoremap a :noh<ENTER>

" grab the text that was just pasted
nnoremap gp `[v`]

" scroll current line to 9th line from the top
nnoremap tt 8kzt8j

" CTRL-W for NERDTree
nnoremap <C-w> :NERDTreeToggle<CR>

" _ is the black hold register
" delete without putting text into buffer
nnoremap <leader>d "_d
vnoremap <leader>d "_d

" change word with text in default buffer
"nnoremap cp "_dwhp
