" let g:pathogen_disabled = ["nerdtree"]
execute pathogen#infect()

set noautochdir
" add current directory to path
set path+=**
" show all options when fuzzy finding
set wildmenu
set complete-=i

" for tags
set tags=./tags;$HOME
" Open definition in vertical split
nnoremap <C-\> :vsp <CR>:exec("tag ".expand("<cword>"))<CR>
" Open definition in horizontal split
" nnoremap <C-[> <C-w><C-]>
" nnoremap <esc>^[ <esc>^[
" nnoremap ^[ ^[
" Open definition in new tab
nnoremap <silent> <leader><C-]> <C-w><C-]><C-w>T
" Open tagbar
nnoremap gc :TagbarToggle<CR>

set expandtab
set tabstop=4
set shiftwidth=4
"set softtabstop=4
set nowrap

" easier pane navigation
nnoremap <C-J> <C-W><C-J>
nnoremap <C-K> <C-W><C-K>
nnoremap <C-L> <C-W><C-L>
nnoremap <C-H> <C-W><C-H>

" more natural splitting
set splitbelow
set splitright

set statusline=%F%m%r%h%w\ %=[FORMAT=%{&ff}]\ [LEN=%L]\ [POS=%04l,%04v][%p%%]
set statusline+=%#warningmsg#
set statusline+=%*
set laststatus=2
set number
"set relativenumber 


set mouse=a
" allow dragging inside tmux
set ttymouse=xterm2
set clipboard=unnamed

set backspace=indent,eol,start

set hlsearch
set ignorecase
set smartcase
set vb
" Un-highlight search
nnoremap <silent> <CR> :noh<CR>
nnoremap <silent> <C-c> :noh<CR>

" grab the text that was just pasted
nnoremap gp `[v`]

" scroll current line to 9th line from the top
nnoremap gb 8kzt8j
nmap gB gggb
nmap `` ``gb
nmap '' ''gb

let g:netrw_liststyle=3
" CTRL-N for NERDTree
nnoremap <C-n> :NERDTreeToggle<CR>
let NERDTreeIgnore = ["\.pyc$", "^__init__.py$"]

" _ is the black hole register
" delete without putting text into buffer
nnoremap <leader>d "_d
vnoremap <leader>d "_d

" change word with text in default buffer
"nnoremap cp "_dwhp

" Toggle Syntastic
nnoremap _ :SyntasticToggleMode<ENTER>

" Close Syntastic error window
nnoremap , :SyntasticReset<ENTER>

set guifont="Menlo Regular:h12"

" highlight past column 80
let &colorcolumn=join(range(81,81),",")

set autoread

hi TabLine      ctermfg=White  ctermbg=253  cterm=NONE
hi TabLineFill  ctermfg=White  ctermbg=253  cterm=NONE
hi TabLineSel   ctermfg=Black  ctermbg=253  cterm=NONE

" count things selected in visual mode
set showcmd

syntax enable
set background=dark
colorscheme railscasts
filetype plugin on

" filetype indent on
set autoindent
set nocindent

let g:syntastic_python_checkers = ["flake8", "pylint"]

let g:syntastic_always_populate_loc_list = 1
let g:syntastic_auto_loc_list = 1
let g:syntastic_check_on_open = 0
let g:syntastic_check_on_wq = 0
" Ignore certain errors
let g:syntastic_quiet_messages = { 'regex' : [
    \ "E501", "E128", "E261",
    \ "missing-docstring", "invalid-name", "too-few-public-methods", "fixme", 
    \ "no-value-for-parameter", "line-too-long"
    \ ] }
