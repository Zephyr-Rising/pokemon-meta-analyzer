import pandas as pd
import numpy as np
import plotly.graph_objects as go
import plotly.express as px
from plotly.subplots import make_subplots
from scipy import stats
import random
import re
import warnings
warnings.filterwarnings('ignore')

MIN_SAMPLE = 15
SMOOTHING_ALPHA = 2
N_SIMS = 10_000
N_PLAYERS = 256
SWISS_ROUNDS = 8
CUT_THRESHOLD = 16

DECK_PALETTE = [
    '#4338ca', '#0d9488', '#d97706', '#dc2626', '#7c3aed',
    '#2563eb', '#059669', '#ea580c', '#e11d48', '#8b5cf6',
    '#0284c7', '#16a34a', '#ca8a04', '#be123c', '#6d28d9',
    '#0891b2', '#65a30d', '#c2410c', '#9f1239', '#5b21b6',
    '#0e7490', '#4d7c0f', '#9a3412', '#881337', '#4c1d95',
    '#155e75', '#3f6212', '#7c2d12', '#701a75', '#312e81',
]

TIER_COLORS = {'All': '#4338ca', 'Upper50': '#0d9488', 'Upper25': '#d97706'}
TIER_RATING_COLORS = {'S': '#eab308', 'A': '#059669', 'B': '#6366f1', 'C': '#f59e0b', 'D': '#ef4444'}
FAVORABLE_COLOR = '#16a34a'
UNFAVORABLE_COLOR = '#dc2626'

HEATMAP_SCALE = [[0, '#be123c'], [0.25, '#f87171'], [0.5, '#f5f5f5'], [0.75, '#6ee7b7'], [1, '#059669']]

FONT_STACK = "'Inter', 'Segoe UI', system-ui, -apple-system, sans-serif"

META_TEMPLATE = go.layout.Template(
    layout=go.Layout(
        font=dict(family=FONT_STACK, color='#374151', size=13),
        title=dict(font=dict(size=18, color='#1e293b'), x=0.02, xanchor='left'),
        paper_bgcolor='rgba(0,0,0,0)',
        plot_bgcolor='#ffffff',
        xaxis=dict(
            gridcolor='#f0f0f0', gridwidth=1, linecolor='#d1d5db', linewidth=1,
            zeroline=False, tickfont=dict(size=11, color='#64748b'),
            title_font=dict(size=13, color='#475569'),
        ),
        yaxis=dict(
            gridcolor='#f0f0f0', gridwidth=1, linecolor='#d1d5db', linewidth=1,
            zeroline=False, tickfont=dict(size=11, color='#64748b'),
            title_font=dict(size=13, color='#475569'),
        ),
        hoverlabel=dict(
            bgcolor='white', bordercolor='#e2e8f0',
            font=dict(family=FONT_STACK, size=12, color='#1e293b'),
        ),
        legend=dict(
            bgcolor='rgba(255,255,255,0.9)', bordercolor='#e2e8f0', borderwidth=1,
            font=dict(size=11),
        ),
    )
)

import plotly.io as pio
pio.templates['meta'] = META_TEMPLATE
pio.templates.default = 'meta'

def make_short_name(name, max_len=14):
    parts = name.split('-')
    if len(parts) <= 2:
        return name.title()
    abbrev = '-'.join(p[:4].title() for p in parts[:2])
    suffix = '-' + parts[-1] if parts[-1] in ('ex', 'box', 'dri', 'twm', 'scr') else ''
    result = abbrev + suffix
    return result[:max_len] if len(result) > max_len else result

print("Configuration loaded (v2 — polished theme).")