"""Paper geometry and style, with separate panels and explicit input paths."""
import argparse
import os
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from cycler import cycler
from matplotlib.ticker import ScalarFormatter, MultipleLocator
from plot_style import set_mpl_defaults, get_series_styles, setup_grid, apply_scalar_formatter, add_ylim_padding
from plot_data import read_curves, REPO


def draw(fig_id, path):
    # AE FIX: isolate rcParams so report import order cannot change figure fonts.
    plt.rcdefaults()
    curves, original = read_curves(path, fig_id)
    if fig_id == 'fig6':
        set_mpl_defaults()
        plt.rcParams.update({'axes.prop_cycle':cycler('color',['#4E79A7','#F28E2B','#E15759','#76B7B2','#AF7AA1']),
            'font.size':30,'axes.labelsize':30,'xtick.labelsize':30,'ytick.labelsize':30,
            'legend.fontsize':30,'legend.markerscale':0.85,'legend.handlelength':1.8,'lines.markersize':8})
        styles=[('-','x'),('--','o'),(':','s'),('-.','^'),('-','D')]
        fig, ax=plt.subplots(figsize=(12,6))
        for (name, points),(ls,mk) in zip(curves.items(),styles):
            ax.plot([p[1] for p in points],[p[2] for p in points],linestyle=ls,marker=mk,label=name)
        ax.set_xlabel('Throughput (TPS)',labelpad=8)
        ax.set_ylabel('End-to-End Latency (ms)',labelpad=8)
        ax.xaxis.set_major_formatter(ScalarFormatter(useMathText=True))
        ax.yaxis.set_major_formatter(ScalarFormatter(useMathText=True))
        ax.yaxis.set_major_locator(MultipleLocator(1000)); ax.set_ylim(top=10000)
        setup_grid(ax)
        handles,labels=ax.get_legend_handles_labels()
        if len(handles)<=2: ax.legend(handles,labels,loc='upper left',frameon=False)
        else:
            left=ax.legend(handles[:2],labels[:2],loc='upper left',bbox_to_anchor=(0,1.05),frameon=False)
            ax.add_artist(left)
            ax.legend(handles[2:],labels[2:],loc='upper left',bbox_to_anchor=(0.55,1.05),frameon=False)
        fig.tight_layout()
        return {'':fig}
    set_mpl_defaults()
    ticks=sorted({p[0] for points in curves.values() for p in points})
    result={}
    for metric,col in [('throughput',1),('latency',2)]:
        fig,ax=plt.subplots(figsize=(8,6))
        # Original scripts use ordinal row positions, including the malformed S2 x.
        # Real AE stats instead map each fault to its actual position on the axis.
        style_map={name:style for name,style in zip(read_curves(REPO/'runs/reference/original'/('alg_tee_nodes_WAN.csv' if fig_id=='fig3' else 'sets_vs_tee_nodes_long.csv'),fig_id)[0],get_series_styles())}
        color_map={name:['#4E79A7','#F28E2B','#E15759','#76B7B2'][i%4] for i,name in enumerate(style_map)}
        for name,points in curves.items():
            x=list(range(len(points))) if original else [ticks.index(p[0]) for p in points]
            ls,mk=style_map[name]
            ax.plot(x,[p[col] for p in points],linestyle=ls,marker=mk,label=name,color=color_map[name])
        setup_grid(ax); ax.set_xticks(range(len(ticks))); ax.set_xticklabels([str(x) for x in ticks])
        apply_scalar_formatter(ax)
        ax.set_ylabel('Throughput (kTPS)' if col==1 else 'Latency (ms)',labelpad=8)
        if fig_id=='fig3':
            if col==1:
                ax.set_ylim(0,4); ax.legend(loc='upper left',bbox_to_anchor=(-0.02,1),frameon=False,ncol=2,columnspacing=0.8)
            else:
                add_ylim_padding(ax); ax.set_ylim(top=3000); ax.legend(loc='upper left',frameon=False,ncol=1)
        else: ax.legend(loc='upper right' if col==1 else 'upper left',frameon=False,ncol=1 if col==1 else 2)
        fig.tight_layout(); result[metric]=fig
    return result


def plot(fig_id, path, out_pdf):
    from matplotlib.backends.backend_pdf import PdfPages
    out_pdf=Path(out_pdf); out_pdf.parent.mkdir(parents=True,exist_ok=True)
    panels=draw(fig_id,path)
    # Multipage figure PDF preserves the paper's individual panel geometry.
    with PdfPages(out_pdf) as pdf:
        for suffix,fig in panels.items():
            stem=out_pdf.stem+('_'+suffix if suffix else '')
            pdf.savefig(fig,bbox_inches='tight',dpi=300)
            if suffix: fig.savefig(out_pdf.with_name(stem+'.pdf'),bbox_inches='tight',dpi=300)
            fig.savefig(out_pdf.with_name(stem+'.png'),bbox_inches='tight',dpi=150)
            plt.close(fig)
    print(f'Saved: {out_pdf}')


def main(fig_id):
    p=argparse.ArgumentParser()
    p.add_argument('--input',type=Path)
    p.add_argument('--output',type=Path)
    args=p.parse_args()
    exp={'fig3':'experiment1','fig4':'experiment2','fig6':'experiment3'}[fig_id]
    rd=os.environ.get('AE_RUN_DIR')
    default=(Path(rd)/'raw'/exp/'stats.txt') if rd else REPO/'experiments_reproduction'/exp/'stats.txt'
    output=(Path(rd)/'figures'/f'{fig_id}.pdf') if rd else REPO/'experiments_reproduction'/exp/'results'/f'{fig_id}.pdf'
    plot(fig_id,args.input or default,args.output or output)
