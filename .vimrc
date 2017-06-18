execute pathogen#infect()

set noautochdir
" add current directory to path
set path+=**
" show all options when fuzzy finding
set wildmenu
" do not autocomplete from included files
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
set softtabstop=4
set nowrap

" easier pane navigation
nnoremap <C-J> <C-W><C-J>
nnoremap <C-K> <C-W><C-K>
nnoremap <C-L> <C-W><C-L>
nnoremap <C-H> <C-W><C-H>

" more natural splitting
set splitbelow
set splitright

set laststatus=2
set number
"set relativenumber


set mouse=a
" allow dragging inside tmux
set ttymouse=xterm2

set backspace=indent,eol,start

set hlsearch
set ignorecase
set smartcase
set vb
" Un-highlight search
nnoremap <silent> <CR> :noh<CR>
nnoremap <silent> <C-c> :noh<CR>
nnoremap <silent> <esc> :noh<CR>

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
nnoremap _ :SyntasticToggleMode<CR>

" Close Syntastic error window
nnoremap , :SyntasticReset<CR>

set guifont="Menlo Regular:h12"

" highlight past column 80
let &colorcolumn=join(range(81,81),",")

set autoread

"hi TabLine      ctermfg=White  ctermbg=253  cterm=NONE
"hi TabLineFill  ctermfg=White  ctermbg=253  cterm=NONE
"hi TabLineSel   ctermfg=Black  ctermbg=253  cterm=NONE

" count things selected in visual mode
set showcmd

syntax enable
set background=dark
colorscheme railscasts
filetype plugin on

filetype indent plugin on
set autoindent
set cindent
let g:pyindent_open_paren = '&sw'
let g:pyindent_nested_paren = '&sw'
let g:pyindent_continue = '&sw'

let g:airline_section_x = ""
let g:airline_theme = "luna"
let g:airline_section_z = "%p%%  %l/%L  ln: %v"
let g:airline#extensions#tabline#enabled = 1
let g:airline#extensions#whitespace#enabled = 0
let g:airline#extensions#tabline#show_buffers = 0
let g:airline#extensions#tabline#fnamemod = ':t'

let g:syntastic_python_checkers = ["flake8", "pylint"]
let g:syntastic_c_checkers = ["gcc"]

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
