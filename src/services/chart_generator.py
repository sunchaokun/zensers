# -*- coding: utf-8 -*-
"""
Chart Generation Service
========================

Generates professional data charts based on matplotlib, supporting multiple chart types.

Supported chart types:
1. bar - Bar chart
2. hbar - Horizontal bar chart
3. bar_line - Bar + Line combination chart
4. pie - Pie chart
5. line - Line chart
6. radar - Radar chart
7. scatter - Scatter plot
8. bubble - Bubble chart
9. waterfall - Waterfall chart
10. quadrant - Quadrant chart

Design doc: docs/KNOWLEDGE_BASE/02_ARCHITECTURE/ORCHESTRATOR_REDESIGN.md
"""

import logging
import os
import tempfile
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import matplotlib
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.patches import FancyBboxPatch
import numpy as np

logger = logging.getLogger(__name__)

# Set matplotlib backend
matplotlib.use('Agg')

# Set Chinese fonts
plt.rcParams['font.sans-serif'] = ['Microsoft YaHei', 'SimHei', 'SimSun', 'DejaVu Sans']
plt.rcParams['axes.unicode_minus'] = False


class ChartType(Enum):
    """Chart type"""
    BAR = "bar"
    HBAR = "hbar"
    BAR_LINE = "bar_line"
    PIE = "pie"
    LINE = "line"
    RADAR = "radar"
    SCATTER = "scatter"
    BUBBLE = "bubble"
    WATERFALL = "waterfall"
    QUADRANT = "quadrant"


@dataclass
class ChartConfig:
    """Chart configuration"""
    chart_type: ChartType
    title: str
    data: Dict[str, Any]
    xlabel: str = ""
    ylabel: str = ""
    caption: str = ""
    source: str = "Public data compilation"
    width: int = 9
    height: int = 5.5
    dpi: int = 150


@dataclass
class ChartResult:
    """Chart generation result"""
    success: bool
    image_path: Optional[str] = None
    error: Optional[str] = None


class ChartGenerator:
    """
    Chart Generator
    
    Generates professional format data charts, supporting multiple types.
    
    Usage example:
        generator = ChartGenerator()
        
        # Generate market share bar chart
        result = generator.generate(ChartConfig(
            chart_type=ChartType.BAR,
            title="Global Power Battery Market Share (2023)",
            data={
                "categories": ["CATL", "BYD", "LG Energy", "Panasonic", "SK On"],
                "values": [37.4, 15.7, 13.6, 7.3, 5.4]
            },
            ylabel="Market Share (%)"
        ))
    """
    
    # Professional 12-color palette
    COLORS = {
        'navy_blue': (26, 39, 68),
        'gold': (201, 162, 39),
        'charcoal': (51, 51, 51),
        'success': (39, 174, 96),
        'warning': (230, 126, 34),
        'light_gold': (255, 248, 220),
        'white': (255, 255, 255),
        'slate': (71, 95, 125),
        'teal': (38, 166, 154),
        'coral': (239, 131, 107),
        'plum': (142, 85, 142),
        'sand': (203, 174, 127),
    }
    
    # Extended color palette (12 colors, RGB tuples for matplotlib)
    PALETTE_12 = [
        (26/255, 39/255, 68/255),     # navy_blue
        (201/255, 162/255, 39/255),   # gold
        (71/255, 95/255, 125/255),    # slate
        (38/255, 166/255, 154/255),   # teal
        (239/255, 131/255, 107/255),  # coral
        (142/255, 85/255, 142/255),   # plum
        (203/255, 174/255, 127/255),  # sand
        (74/255, 144/255, 217/255),   # steel blue
        (126/255, 181/255, 166/255),  # sage
        (232/255, 168/255, 124/255),  # peach
        (212/255, 165/255, 116/255),  # tan
        (201/255, 162/255, 39/255),   # gold variant
    ]
    
    def __init__(self, output_dir: Optional[str] = None):
        """
        Initialize chart generator
        
        Args:
            output_dir: Chart output directory, defaults to temp directory
        """
        self.output_dir = Path(output_dir) if output_dir else Path(tempfile.mkdtemp())
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        # RGB color conversion
        self._navy = self._rgb(*self.COLORS['navy_blue'])
        self._gold = self._rgb(*self.COLORS['gold'])
        self._char = self._rgb(*self.COLORS['charcoal'])
        self._chart_counter = 0
    
    def _rgb(self, r: int, g: int, b: int) -> Tuple[float, float, float]:
        """Convert RGB to matplotlib format"""
        return (r/255, g/255, b/255)
    
    def generate(self, config: ChartConfig) -> ChartResult:
        """
        Generate chart
        
        Args:
            config: Chart configuration
            
        Returns:
            ChartResult generation result
        """
        try:
            # Select generation method based on type
            handlers = {
                ChartType.BAR: self._generate_bar,
                ChartType.HBAR: self._generate_hbar,
                ChartType.BAR_LINE: self._generate_bar_line,
                ChartType.PIE: self._generate_pie,
                ChartType.LINE: self._generate_line,
                ChartType.RADAR: self._generate_radar,
                ChartType.SCATTER: self._generate_scatter,
                ChartType.BUBBLE: self._generate_bubble,
                ChartType.WATERFALL: self._generate_waterfall,
                ChartType.QUADRANT: self._generate_quadrant,
            }
            
            handler = handlers.get(config.chart_type)
            if not handler:
                return ChartResult(
                    success=False,
                    error=f"Unsupported chart type: {config.chart_type}"
                )
            
            # Generate chart
            image_path = handler(config)
            
            return ChartResult(
                success=True,
                image_path=image_path
            )
            
        except Exception as e:
            logger.error(f"Chart generation failed: {e}", exc_info=True)
            return ChartResult(
                success=False,
                error=str(e)
            )
    
    def _create_figure(self, config: ChartConfig) -> Tuple[plt.Figure, plt.Axes]:
        """Create figure"""
        fig, ax = plt.subplots(figsize=(config.width, config.height))
        fig.patch.set_facecolor('white')
        ax.set_facecolor('#FAFAFA')
        return fig, ax
    
    def _add_annotations(self, fig: plt.Figure, config: ChartConfig) -> None:
        """Add caption and source text below the chart"""
        if config.caption or config.source:
            text_parts = []
            if config.caption:
                text_parts.append(config.caption)
            if config.source:
                text_parts.append(f"来源：{config.source}")
            fig.text(0.5, 0.01, " | ".join(text_parts),
                    ha='center', fontsize=7, color='#888888', style='italic')
    
    def _save_figure(self, fig: plt.Figure, name: str, config: ChartConfig = None) -> str:
        """Save figure with unique filename"""
        if config:
            self._add_annotations(fig, config)
        self._chart_counter += 1
        image_path = str(self.output_dir / f"{name}_{self._chart_counter}.png")
        fig.savefig(image_path, dpi=150, bbox_inches='tight',
                   facecolor='white', edgecolor='none')
        plt.close(fig)
        return image_path
    
    def _generate_bar(self, config: ChartConfig) -> str:
        """Generate bar chart (single series or grouped)"""
        fig, ax = self._create_figure(config)
        
        data = config.data
        categories = data.get('categories', [])
        
        if 'series' in data:
            # Grouped bar chart
            series_list = data['series']
            n_series = len(series_list)
            x = np.arange(len(categories))
            width = 0.6 / n_series
            
            for i, s in enumerate(series_list):
                s_values = s.get('values', [])
                safe_values = [v if v is not None else np.nan for v in s_values]
                offset = (i - n_series / 2 + 0.5) * width
                color = self.PALETTE_12[i % len(self.PALETTE_12)]
                bars = ax.bar(x + offset, safe_values, width, color=color,
                             alpha=0.85, zorder=3, label=s.get('name', f'Series {i+1}'))
                
                unit = s.get('unit', data.get('unit', ''))
                for bar, val in zip(bars, s_values):
                    if val is None:
                        continue
                    if unit == '%':
                        label = f'{val}%'
                    elif abs(val) >= 10000:
                        label = f'{val/10000:.1f}万'
                    elif abs(val) >= 1:
                        label = f'{val:.1f}'
                    else:
                        label = f'{val:.2f}'
                    ax.text(bar.get_x() + bar.get_width()/2, bar.get_height(),
                           label, ha='center', va='bottom', fontsize=7, color=self._char)
            
            ax.set_xticks(x)
            ax.legend(fontsize=8, loc='best')
        else:
            # Single series bar chart
            values = data.get('values', [])
            x = np.arange(len(categories))
            
            bars = ax.bar(x, values, color=self._navy, alpha=0.85, zorder=3, width=0.6)
            
            unit = data.get('unit', '')
            pct_values = data.get('show_percent', False)
            for bar, val in zip(bars, values):
                if pct_values or unit == '%':
                    label = f'{val}%'
                elif abs(val) >= 10000:
                    label = f'{val/10000:.1f}万'
                elif abs(val) >= 1:
                    label = f'{val:.1f}'
                else:
                    label = f'{val:.2f}'
                ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.5,
                       label, ha='center', va='bottom', fontsize=9, color=self._char)
        
        ax.set_xticks(x)
        ax.set_xticklabels(categories, fontsize=9, rotation=15)
        ax.set_ylabel(config.ylabel, fontsize=10)
        ax.set_title(config.title, fontsize=12, fontweight='bold', pad=12, color=self._char)
        ax.spines['top'].set_visible(False)
        ax.grid(axis='y', linestyle='--', alpha=0.4, zorder=0)
        
        return self._save_figure(fig, f"bar_{hash(config.title) % 10000}", config)
    
    def _generate_hbar(self, config: ChartConfig) -> str:
        """Generate horizontal bar chart"""
        fig, ax = self._create_figure(config)
        
        data = config.data
        labels = data.get('labels', data.get('categories', []))
        values = data.get('values', [])
        
        y = np.arange(len(labels))
        colors = [self._navy] * len(labels)
        
        bars = ax.barh(y, values, color=colors, alpha=0.85, zorder=3)
        
        unit = data.get('unit', '')
        pct_values = data.get('show_percent', False)
        for bar, val in zip(bars, values):
            if pct_values or unit == '%':
                label = f'{val}%'
            elif abs(val) >= 10000:
                label = f'{val/10000:.1f}万'
            elif abs(val) >= 1:
                label = f'{val:.1f}'
            else:
                label = f'{val:.2f}'
            x_pos = bar.get_width() + 5 if val >= 0 else bar.get_width() - 5
            ha = 'left' if val >= 0 else 'right'
            ax.text(x_pos, bar.get_y() + bar.get_height()/2,
                   label, va='center', ha=ha, fontsize=9, color=self._char)
        
        ax.set_yticks(y)
        ax.set_yticklabels(labels, fontsize=10)
        ax.set_xlabel(config.xlabel or config.ylabel, fontsize=10)
        ax.set_title(config.title, fontsize=12, fontweight='bold', pad=12, color=self._char)
        ax.spines['top'].set_visible(False)
        ax.grid(axis='x', linestyle='--', alpha=0.4, zorder=0)
        ax.invert_yaxis()
        
        return self._save_figure(fig, f"hbar_{hash(config.title) % 10000}", config)
    
    def _generate_bar_line(self, config: ChartConfig) -> str:
        fig, ax = self._create_figure(config)

        data = config.data
        years = data.get('years', [])
        bar_values = data.get('bar', [])
        line_values = data.get('line', [])
        bar_label = data.get('bar_label', '')
        line_label = data.get('line_label', '')

        x = np.arange(len(years))
        w = 0.5

        bars = ax.bar(x, bar_values, w, color=self._navy, alpha=0.85, zorder=3, label=bar_label)

        bar_unit = data.get('bar_unit', '')
        for bar, val in zip(bars, bar_values):
            if bar_unit == '%':
                lbl = f'{val}%'
            elif abs(val) >= 10000:
                lbl = f'{val/10000:.1f}万'
            elif abs(val) >= 1:
                lbl = f'{val:.1f}'
            else:
                lbl = f'{val:.2f}'
            ax.text(bar.get_x() + bar.get_width()/2, bar.get_height(),
                   lbl, ha='center', va='bottom', fontsize=8, color=self._char)

        ax2 = ax.twinx()
        clean_line = [v if v is not None else np.nan for v in line_values]
        ax2.plot(x, clean_line, 'o-', color=self._gold, linewidth=2.5,
                markersize=7, label=line_label, zorder=4)

        for i, val in enumerate(line_values):
            if val is not None and not (isinstance(val, float) and np.isnan(val)):
                label = f'{val}%' if data.get('line_unit') == '%' else f'{val:.1f}'
                ax2.annotate(label, (x[i], val), textcoords="offset points",
                            xytext=(0, 10), ha='center', fontsize=8, color=self._gold)

        ax2.set_ylabel(line_label, color=self._gold, fontsize=10)
        ax2.tick_params(axis='y', labelcolor=self._gold)

        lines1, labels1 = ax.get_legend_handles_labels()
        lines2, labels2 = ax2.get_legend_handles_labels()
        ax.legend(lines1 + lines2, labels1 + labels2, fontsize=9, loc='upper left')

        ax.set_xticks(x)
        ax.set_xticklabels(years, fontsize=9)
        ax.set_ylabel(config.ylabel or bar_label, fontsize=10)
        ax.set_title(config.title, fontsize=12, fontweight='bold', pad=12, color=self._char)
        ax.spines['top'].set_visible(False)
        ax.grid(axis='y', linestyle='--', alpha=0.4, zorder=0)

        return self._save_figure(fig, f"barline_{hash(config.title) % 10000}", config)
    
    def _generate_pie(self, config: ChartConfig) -> str:
        """Generate pie chart, auto-downgrade to bar if >6 items"""
        data = config.data
        labels = data.get('labels', data.get('categories', []))
        values = data.get('values', [])
        
        # P1: Auto-downgrade to bar chart if > 6 items
        if len(values) > 6:
            bar_config = ChartConfig(
                chart_type=ChartType.BAR,
                title=config.title,
                data=config.data,
                xlabel=config.xlabel,
                ylabel=config.ylabel,
                caption=config.caption,
                source=config.source,
                width=config.width,
                height=config.height,
                dpi=config.dpi,
            )
            return self._generate_bar(bar_config)
        
        fig, ax = plt.subplots(figsize=(8, 8))
        fig.patch.set_facecolor('white')
        
        explode = data.get('explode', [0.02] * len(values))
        colors = self.PALETTE_12[:len(values)]
        
        wedges, texts, autotexts = ax.pie(
            values, labels=labels, autopct='%1.1f%%',
            colors=colors,
            explode=explode[:len(values)],
            shadow=False, startangle=90
        )
        
        for i, autotext in enumerate(autotexts):
            col = colors[i] if i < len(colors) else colors[0]
            try:
                rgb = plt.matplotlib.colors.to_rgb(col)
                luminance = 0.299 * rgb[0] + 0.587 * rgb[1] + 0.114 * rgb[2]
                autotext.set_color('white' if luminance < 0.55 else '#333333')
            except Exception:
                autotext.set_color('white')
            autotext.set_fontsize(9)
            autotext.set_fontweight('bold')
        
        ax.set_title(config.title, fontsize=12, fontweight='bold', pad=12, color=self._char)
        
        return self._save_figure(fig, f"pie_{hash(config.title) % 10000}", config)
    
    def _generate_line(self, config: ChartConfig) -> str:
        """Generate line chart"""
        fig, ax = self._create_figure(config)
        
        data = config.data
        years = data.get('years', [])
        scenarios = data.get('scenarios', {})
        
        x = np.arange(len(years))
        line_colors = [self._navy, self._gold, '#7EB5A6', '#E8836B', '#8E558E', '#CBAE7F', '#4A90D9', '#5B8DB8']
        line_styles = ['-', '--', '-.', ':']

        for i, (label, vals) in enumerate(scenarios.items()):
            col = line_colors[i % len(line_colors)]
            ls = line_styles[i % len(line_styles)]
            ax.plot(x, vals, marker='o', linewidth=2, color=col,
                   linestyle=ls, label=label, zorder=3)
        
        ax.set_xticks(x)
        ax.set_xticklabels(years, fontsize=9)
        ax.set_ylabel(config.ylabel, fontsize=10)
        ax.set_title(config.title, fontsize=12, fontweight='bold', pad=12, color=self._char)
        ax.legend(fontsize=9, loc='upper left')
        ax.spines['top'].set_visible(False)
        ax.grid(linestyle='--', alpha=0.4, zorder=0)
        
        return self._save_figure(fig, f"line_{hash(config.title) % 10000}", config)
    
    def _generate_radar(self, config: ChartConfig) -> str:
        data = config.data
        categories = data.get('categories', [])

        N = len(categories)
        angles = [n / float(N) * 2 * np.pi for n in range(N)]
        angles_closed = angles + angles[:1]

        fig = plt.figure(figsize=(8, 8))
        ax = plt.subplot(111, polar=True)
        fig.patch.set_facecolor('white')

        radar_colors = [self._navy, self._gold, '#7EB5A6', '#E8836B', '#8E558E']
        radar_fills = [0.25, 0.15, 0.15, 0.15, 0.15]

        if "scenarios" in data:
            scenarios = data.get("scenarios", {})
            for i, (label, vals) in enumerate(scenarios.items()):
                closed_vals = vals + vals[:1]
                color = radar_colors[i % len(radar_colors)]
                fill_alpha = radar_fills[min(i, len(radar_fills)-1)]
                ax.plot(angles_closed, closed_vals, 'o-', linewidth=2,
                       color=color, alpha=0.8, label=label)
                ax.fill(angles_closed, closed_vals, alpha=fill_alpha, color=color)
            ax.legend(fontsize=9, loc='upper right', bbox_to_anchor=(1.3, 1.1))
        else:
            values = data.get('values', [])
            closed_vals = values + values[:1]
            ax.plot(angles_closed, closed_vals, 'o-', linewidth=2, color=self._navy, alpha=0.8)
            ax.fill(angles_closed, closed_vals, alpha=0.25, color=self._navy)

        ax.set_thetagrids(np.degrees(angles), categories, fontsize=9)
        all_vals = []
        if "scenarios" in data:
            for vals in data["scenarios"].values():
                all_vals.extend([v for v in vals if isinstance(v, (int, float))])
        else:
            all_vals = data.get('values', [])
        max_val = max(all_vals) if all_vals else 100
        ax.set_ylim(0, max(max_val * 1.1, 100))
        ax.set_title(config.title, fontsize=12, fontweight='bold', pad=20)

        plt.tight_layout()
        return self._save_figure(fig, f"radar_{hash(config.title) % 10000}", config)
    
    def _generate_scatter(self, config: ChartConfig) -> str:
        """Generate scatter plot"""
        fig, ax = self._create_figure(config)
        
        data = config.data
        x_values = data.get('x', [])
        y_values = data.get('y', [])
        labels = data.get('labels', [])
        
        ax.scatter(x_values, y_values, color=self._navy, alpha=0.6, s=100, zorder=3)
        
        for i, label in enumerate(labels):
            ax.annotate(label, (x_values[i], y_values[i]), xytext=(5, 5),
                       textcoords='offset points', fontsize=9, color=self._char)
        
        ax.set_xlabel(config.xlabel, fontsize=10)
        ax.set_ylabel(config.ylabel, fontsize=10)
        ax.set_title(config.title, fontsize=12, fontweight='bold', pad=12, color=self._char)
        ax.spines['top'].set_visible(False)
        ax.grid(linestyle='--', alpha=0.4, zorder=0)
        
        return self._save_figure(fig, f"scatter_{hash(config.title) % 10000}", config)
    
    def _generate_bubble(self, config: ChartConfig) -> str:
        """Generate bubble chart"""
        fig, ax = self._create_figure(config)
        
        data = config.data
        sectors = data.get('sectors', [])
        
        for s in sectors:
            ax.scatter(s['x'], s['y'], s=s.get('size', 10) * 50,
                      color=self._navy, alpha=0.5, zorder=3)
            ax.annotate(s['name'], (s['x'], s['y']), xytext=(5, 5),
                       textcoords='offset points', fontsize=9, color=self._char)
        
        ax.set_xlabel(config.xlabel, fontsize=10)
        ax.set_ylabel(config.ylabel, fontsize=10)
        ax.set_title(config.title, fontsize=12, fontweight='bold', pad=12, color=self._char)
        ax.spines['top'].set_visible(False)
        ax.grid(linestyle='--', alpha=0.4, zorder=0)
        
        return self._save_figure(fig, f"bubble_{hash(config.title) % 10000}", config)
    
    def _generate_waterfall(self, config: ChartConfig) -> str:
        """Generate waterfall chart with cumulative offset"""
        fig, ax = self._create_figure(config)
        
        data = config.data
        factors = data.get('factors', [])
        
        labels = [f['label'] for f in factors]
        values = [f['value'] for f in factors]
        is_total = [f.get('is_total', False) for f in factors]
        
        x = np.arange(len(labels))
        
        # Calculate bottom positions for each bar
        bottoms = []
        cumulative = 0
        for i, (val, it) in enumerate(zip(values, is_total)):
            if it:
                bottoms.append(0)
                cumulative = val
            else:
                bottoms.append(cumulative)
                cumulative += val
        
        # Assign colors
        colors = []
        for v, it in zip(values, is_total):
            if it:
                colors.append(self._navy)
            elif v > 0:
                colors.append('#4CAF50')
            else:
                colors.append('#F44336')
        
        bars = ax.bar(x, values, bottom=bottoms, color=colors, alpha=0.85, zorder=3)
        
        for bar, val, bot in zip(bars, values, bottoms):
            h = bar.get_height()
            y_pos = bot + h if h >= 0 else bot
            if abs(val) >= 10000:
                label = f'{val/10000:+.1f}万'
            elif abs(val) >= 1:
                label = f'{val:+.1f}'
            else:
                label = f'{val:+.2f}'
            ax.text(bar.get_x() + bar.get_width()/2, y_pos,
                   label, ha='center', va='bottom' if h >= 0 else 'top',
                   fontsize=8, color=self._char)
        
        # Add connector lines between bars
        for i in range(len(values) - 1):
            if is_total[i + 1]:
                continue
            top = (bottoms[i] + values[i]) if not is_total[i] else values[i]
            ax.plot([x[i] + 0.4, x[i + 1] - 0.4], [top, top],
                   color='gray', linewidth=0.5, linestyle='--', zorder=2)
        
        ax.set_xticks(x)
        ax.set_xticklabels(labels, fontsize=8, rotation=20)
        ax.set_ylabel(config.ylabel, fontsize=10)
        ax.axhline(y=0, color='black', linewidth=0.5)
        ax.set_title(config.title, fontsize=12, fontweight='bold', pad=12, color=self._char)
        ax.spines['top'].set_visible(False)
        ax.grid(axis='y', linestyle='--', alpha=0.4, zorder=0)
        
        return self._save_figure(fig, f"waterfall_{hash(config.title) % 10000}", config)
    
    def _generate_quadrant(self, config: ChartConfig) -> str:
        """Generate quadrant chart"""
        fig, ax = self._create_figure(config)
        
        ax.set_xlim(0, 10)
        ax.set_ylim(0, 10)
        ax.axhline(y=5, color='gray', linewidth=1, linestyle='--', alpha=0.5)
        ax.axvline(x=5, color='gray', linewidth=1, linestyle='--', alpha=0.5)
        
        # Quadrant labels
        q_labels = ['利基\n(低能力/小规模)', '领导者\n(高能力/大规模)',
                   '挑战者\n(高能力/小规模)', '跟随者\n(低能力/大规模)']
        positions = [(2.5, 2.5), (7.5, 7.5), (2.5, 7.5), (7.5, 2.5)]
        
        for pos, label in zip(positions, q_labels):
            ax.text(pos[0], pos[1], label, ha='center', va='center',
                   fontsize=8, color='gray', alpha=0.7)
        
        # Draw players
        data = config.data
        for p in data.get('players', []):
            size = p.get('size', 1) * 80
            ax.scatter(p['x'], p['y'], s=size, color=self._navy, alpha=0.6, zorder=5)
            ax.annotate(p['name'], (p['x'], p['y']), xytext=(5, 5),
                       textcoords='offset points', fontsize=9, color=self._char)
        
        ax.set_xlabel(config.xlabel, fontsize=10)
        ax.set_ylabel(config.ylabel, fontsize=10)
        ax.text(5, 5.3, config.xlabel or '规模', ha='center', fontsize=8, color='gray')
        ax.text(5.3, 5, config.ylabel or '能力', ha='center', va='center', fontsize=8,
               color='gray', rotation=90)
        ax.set_title(config.title, fontsize=12, fontweight='bold', pad=12, color=self._char)
        ax.spines['top'].set_visible(False)
        ax.spines['right'].set_visible(False)
        
        return self._save_figure(fig, f"quadrant_{hash(config.title) % 10000}", config)


# Export
__all__ = ["ChartGenerator", "ChartConfig", "ChartType", "ChartResult"]
