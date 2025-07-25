""""""" STUFF THAT WORKS EVERYWHERE """""""

" stay in root dir no matter which file
set noautochdir
" add current directory to path
set path+=**
" show all options when fuzzy finding
set wildmenu
" ignore files
set wildignore=*.pyc,*/node_modules/*
" do not autocomplete from included files
set complete-=i
" grab current file path
nnoremap <silent> cp :let @+ = expand('%:p')<CR>


" tabs
set expandtab
set tabstop=4 " deals with tab characters
set softtabstop=4 " deals with <tab> and <backspace> keypresses
set shiftwidth=4 " deals with << and >>
set nowrap
autocmd FileType css setlocal shiftwidth=2 tabstop=2 softtabstop=2
autocmd FileType html setlocal shiftwidth=2 tabstop=2 softtabstop=2
autocmd FileType javascript setlocal shiftwidth=2 tabstop=2 softtabstop=2


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


" in-buffer search
set hlsearch
set ignorecase
set smartcase
set vb
" Un-highlight search
" nnoremap <silent> <CR> :noh<CR>
nnoremap <silent> <C-c> :noh<CR>
" nnoremap <silent> <esc> :noh<CR>
" nnoremap <silent> <esc> :noh<CR><esc>


" navigation
" grab the text that was just pasted
" nnoremap gp `[v`]
set noek


" scroll current line to 9th line from the top
nnoremap gb 8kzt8j
nmap gB gggb
nmap `` ``gb
nmap '' ''gb


" file browsing
let g:netrw_liststyle=3


" text editing
" nnoremap <CR> o<esc> " conflict with Ack
" nnoremap <S-CR> O<esc> " conflict with Ack
" _ is the black hole register
" delete without putting text into buffer
nnoremap <leader>d "_d
vnoremap <leader>d "_d


" change word with text in default buffer
"nnoremap cp "_dwhp


" Strip trailing whitespace
fun! <SID>StripTrailingWhitespaces()
    let l = line(".")
    let c = col(".")
    %s/\s\+$//e
    call cursor(l, c)
endfun

autocmd FileType python autocmd BufWritePre <buffer> :call <SID>StripTrailingWhitespaces()


" aesthetics
set guifont="Menlo Regular:h12"
" for non-english characters
set fileencoding=utf-8


" highlight past column 80
let &colorcolumn=join(range(81,81),",")
:hi ColorColumn ctermbg=grey guibg=grey


set autoread


"hi TabLine      ctermfg=White  ctermbg=253  cterm=NONE
"hi TabLineFill  ctermfg=White  ctermbg=253  cterm=NONE
"hi TabLineSel   ctermfg=Black  ctermbg=253  cterm=NONE


" count things selected in visual mode
set showcmd


syntax enable
set background=dark
filetype plugin indent on

""""""" PLUGIN-SPECIFIC STUFF """""""

let g:pathogen_disabled = ['syntastic', 'vim-gitgutter', 'ale']
execute pathogen#infect()
execute pathogen#helptags()


" for fuzzy finding
set rtp+=/usr/local/bin/fzf


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

" reload file as it changes on disk
set autoread


" ctrl-p
let g:ctrlp_switch_buffer = 'Et'
let g:ctrlp_open_multiple_files = 't'
let g:ctrlp_map = '<c-p>'
let g:ctrlp_working_path_mode = 'ra'


" tabs
set expandtab
set tabstop=4 " deals with tab characters
set softtabstop=4 " deals with <tab> and <backspace> keypresses
set shiftwidth=4 " deals with << and >>
set nowrap
autocmd FileType css setlocal shiftwidth=2 tabstop=2 softtabstop=2
autocmd FileType html setlocal shiftwidth=2 tabstop=2 softtabstop=2
autocmd FileType javascript setlocal shiftwidth=2 tabstop=2 softtabstop=2
autocmd FileType java setlocal shiftwidth=2 tabstop=2 softtabstop=2
autocmd FileType sh setlocal shiftwidth=2 tabstop=2 softtabstop=2


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
set ttymouse=sgr " mac

set backspace=indent,eol,start


" file search
set rtp+=/usr/local/bin/rg
if executable("rg")
    let g:ackprg = "rg\ --vimgrep\ --no-heading\ --ignore-case\ --glob\ '!{tags,.git}'\ --regexp"
endif


" CTRL-N for NERDTree
nnoremap <C-n> :NERDTreeToggle<CR>
let NERDTreeIgnore = ["\.pyc$"]


" linting

" Toggle Syntastic
" nnoremap _ :SyntasticToggleMode<CR>

" Close Syntastic error window
" nnoremap , :SyntasticReset<CR>

let g:syntastic_always_populate_loc_list = 1
let g:syntastic_auto_loc_list = 1
let g:syntastic_check_on_open = 0
let g:syntastic_check_on_wq = 1
let g:syntastic_aggregate_errors = 1
" Ignore certain errors
let g:syntastic_quiet_messages = { 'regex' : [
    \ "E501", "E128", "E261", "E701",
    \ "missing-docstring", "invalid-name", "too-few-public-methods", "fixme",
    \ "no-value-for-parameter", "line-too-long", "dangerous-default-value",
    \ "no-member",
    \ ] }
" let g:syntastic_python_checkers = ["flake8", "pylint"]
let g:syntastic_python_checkers = ["flake8"]
let g:syntastic_c_checkers = ["gcc"]
let g:syntastic_javascript_checkers=['eslint']


colorscheme railscasts


let g:airline_section_x = ""
let g:airline_theme = "bubblegum"
let g:airline_section_z = "%p%%  %l/%L  ln: %v"
let g:airline#extensions#tabline#enabled = 1
let g:airline#extensions#whitespace#enabled = 0
let g:airline#extensions#tabline#show_buffers = 0
let g:airline#extensions#tabline#fnamemod = ':t'
let g:airline#extensions#syntastic#enabled = 1


let g:snipMate = { 'snippet_version' : 1 }

" Disable bell beeps and visual bell flashing
set belloff=all

