"""Diagnostic charts saved as PNGs in <model dir>/images before a model is uploaded to the Model Registry.

Uses matplotlib's object API (Figure + Agg canvas, no pyplot), so it is safe in the background
registration thread.
"""
import os
import numpy as np
import matplotlib
matplotlib.use('Agg')
from matplotlib.figure import Figure
from sklearn.metrics import confusion_matrix, precision_recall_fscore_support, roc_curve, auc

BLUE, ORANGE, GREY, GREEN, RED = '#2a6fdb', '#e8853d', '#8a94a3', '#2e9e6a', '#d64545'
SPLIT_COLORS = {'train': GREY, 'validation': ORANGE, 'test': BLUE}


def save(fig, folder, name):
    fig.tight_layout(); fig.savefig(os.path.join(folder, name), dpi=130); return name


def figure(w=7, h=5): return Figure(figsize=(w, h))


def importance_bar(ax, names, values, color, title):
    order = np.argsort(values)
    ax.barh(np.array(names)[order], np.array(values)[order], color=color)
    ax.set_title(title); ax.set_xlabel('Importance (gain share)')


def pace(folder, engine):
    """Regression diagnostics for the XGBoost lap-time model (Pace Detective)."""
    p = engine.pace; test = p[p.split == 'test']; out = []
    rep = engine.pace_report
    # 1. Predicted vs actual on held-out laps, model and baseline.
    fig = figure(6.5, 6); ax = fig.add_subplot()
    lo, hi = np.percentile(np.r_[test.lap_duration_s, test.model_prediction], [1, 99])
    ax.scatter(test.lap_duration_s, test.baseline_prediction, s=14, alpha=.5, color=GREY, label=f"Rolling baseline (MAE {rep['baseline_mae']:.3f}s)")
    ax.scatter(test.lap_duration_s, test.model_prediction, s=14, alpha=.7, color=BLUE, label=f"XGBoost (MAE {rep['model_mae']:.3f}s)")
    ax.plot([lo, hi], [lo, hi], color='black', lw=1, ls='--', label='Perfect prediction')
    ax.set_xlim(lo - .5, hi + .5); ax.set_ylim(lo - .5, hi + .5)
    ax.set_xlabel('Actual lap time (s)'); ax.set_ylabel('Predicted lap time (s)'); ax.set_title('Held-out laps: predicted vs actual'); ax.legend(fontsize=8)
    out.append(save(fig, folder, 'pace_predicted_vs_actual.png'))
    # 2. Residual distributions, model vs baseline.
    fig = figure(); ax = fig.add_subplot()
    clip = lambda v: np.clip(v, -3, 3)
    bins = np.linspace(-3, 3, 49)
    ax.hist(clip(test.baseline_residual), bins=bins, alpha=.5, color=GREY, label='Rolling baseline')
    ax.hist(clip(test.model_residual), bins=bins, alpha=.6, color=BLUE, label='XGBoost')
    ax.axvline(0, color='black', lw=1)
    ax.set_xlabel('Residual: actual − predicted (s, clipped to ±3)'); ax.set_ylabel('Held-out laps'); ax.set_title('Residual distribution on the test split'); ax.legend()
    out.append(save(fig, folder, 'pace_residual_histogram.png'))
    # 3. Residuals across the race, coloured by chronological split.
    fig = figure(8, 4.5); ax = fig.add_subplot()
    for split, g in p.groupby('split'):
        ax.scatter(g.lap_number, clip(g.model_residual), s=10, alpha=.6, color=SPLIT_COLORS.get(split, GREY), label=split)
    ax.axhline(0, color='black', lw=1)
    for cut in engine.pace_cuts: ax.axvline(cut + .5, color='black', lw=.8, ls=':')
    ax.set_xlabel('Lap number'); ax.set_ylabel('Residual (s, clipped to ±3)'); ax.set_title('Residuals by lap (dotted lines: train / validation / test cut-offs)'); ax.legend()
    out.append(save(fig, folder, 'pace_residuals_by_lap.png'))
    # 4. Test MAE per driver, model vs baseline.
    by = test.groupby('driver_code').agg(model=('model_residual', lambda r: np.abs(r).mean()), baseline=('baseline_residual', lambda r: np.abs(r).mean())).sort_values('model')
    fig = figure(8, 4.5); ax = fig.add_subplot(); x = np.arange(len(by)); w = .4
    ax.bar(x - w / 2, by.baseline, w, color=GREY, label='Rolling baseline'); ax.bar(x + w / 2, by.model, w, color=BLUE, label='XGBoost')
    ax.set_xticks(x); ax.set_xticklabels(by.index, rotation=45); ax.set_ylabel('Test MAE (s)'); ax.set_title('Held-out error per driver'); ax.legend()
    out.append(save(fig, folder, 'pace_mae_by_driver.png'))
    # 5. Feature importance, grouped as in the app.
    imp = rep['importance']
    fig = figure(6.5, 4.5); importance_bar(fig.add_subplot(), [i['name'] for i in imp], [i['value'] for i in imp], BLUE, 'XGBoost feature importance')
    out.append(save(fig, folder, 'pace_feature_importance.png'))
    return out


def dna(folder, engine):
    """Classification diagnostics for the XGBoost driver–car classifier (Driver DNA)."""
    from .engine import DNA_FEATURES, FEATURE_LABELS
    d = engine.dna; test = d[d.id.isin(engine.challenge_ids)]; classes = engine.dna_classes; out = []
    X = test[DNA_FEATURES]; y = test.driver.to_numpy()
    proba = engine.dna_model.predict_proba(X); pred = np.array(classes)[proba.argmax(1)]
    # 1. Confusion matrix (counts and row-normalised recall).
    cm = confusion_matrix(y, pred, labels=classes); norm = cm / np.maximum(cm.sum(1, keepdims=True), 1)
    fig = figure(6, 5.2); ax = fig.add_subplot(); im = ax.imshow(norm, cmap='Blues', vmin=0, vmax=1)
    for i in range(len(classes)):
        for j in range(len(classes)): ax.text(j, i, f'{cm[i, j]}\n{norm[i, j]:.0%}', ha='center', va='center', fontsize=9, color='white' if norm[i, j] > .5 else 'black')
    ax.set_xticks(range(len(classes))); ax.set_xticklabels(classes); ax.set_yticks(range(len(classes))); ax.set_yticklabels(classes)
    ax.set_xlabel('Predicted'); ax.set_ylabel('Actual'); ax.set_title(f"Confusion matrix (accuracy {engine.dna_report['accuracy']:.0%}, chance {1 / len(classes):.0%})")
    fig.colorbar(im, ax=ax, label='Share of actual laps')
    out.append(save(fig, folder, 'dna_confusion_matrix.png'))
    # 2. Per-class precision / recall / F1.
    pr, rc, f1, support = precision_recall_fscore_support(y, pred, labels=classes, zero_division=0)
    fig = figure(7, 4.5); ax = fig.add_subplot(); x = np.arange(len(classes)); w = .27
    for k, (vals, label, color) in enumerate([(pr, 'Precision', BLUE), (rc, 'Recall', ORANGE), (f1, 'F1', GREEN)]):
        ax.bar(x + (k - 1) * w, vals, w, label=label, color=color)
    ax.set_xticks(x); ax.set_xticklabels([f'{c}\n(n={n})' for c, n in zip(classes, support)]); ax.set_ylim(0, 1.05)
    ax.set_title('Per-driver precision, recall and F1 (held-out laps)'); ax.legend()
    out.append(save(fig, folder, 'dna_per_class_metrics.png'))
    # 3. One-vs-rest ROC curves.
    fig = figure(6, 5.5); ax = fig.add_subplot()
    for k, (c, color) in enumerate(zip(classes, [BLUE, ORANGE, RED, GREEN, GREY])):
        truth = (y == c).astype(int)
        if truth.min() == truth.max(): continue
        fpr, tpr, _ = roc_curve(truth, proba[:, k]); ax.plot(fpr, tpr, color=color, label=f'{c} (AUC {auc(fpr, tpr):.2f})')
    ax.plot([0, 1], [0, 1], color='black', ls='--', lw=1)
    ax.set_xlabel('False positive rate'); ax.set_ylabel('True positive rate'); ax.set_title('One-vs-rest ROC (held-out laps)'); ax.legend()
    out.append(save(fig, folder, 'dna_roc_curves.png'))
    # 4. Confidence: max class probability for correct vs wrong calls.
    conf = proba.max(1); right = pred == y
    fig = figure(); ax = fig.add_subplot(); bins = np.linspace(1 / len(classes), 1, 21)
    ax.hist(conf[right], bins=bins, alpha=.7, color=GREEN, label=f'Correct ({right.sum()})'); ax.hist(conf[~right], bins=bins, alpha=.7, color=RED, label=f'Wrong ({(~right).sum()})')
    ax.set_xlabel('Top class probability'); ax.set_ylabel('Held-out laps'); ax.set_title('Prediction confidence: correct vs wrong'); ax.legend()
    out.append(save(fig, folder, 'dna_confidence.png'))
    # 5. Feature importance.
    fig = figure(6.5, 5); importance_bar(fig.add_subplot(), [FEATURE_LABELS[k] for k in DNA_FEATURES], engine.dna_model.feature_importances_, BLUE, 'XGBoost feature importance')
    out.append(save(fig, folder, 'dna_feature_importance.png'))
    return out


def strategy(folder, engine):
    """Diagnostics for the Ridge pace calibration behind the Pitwall simulator."""
    f = engine.strategy_frame; m = engine.strategy_model; out = []
    fitted = m.predict(f); resid = f.lap_duration_s - fitted
    # 1. Fitted vs actual.
    fig = figure(6.5, 6); ax = fig.add_subplot(); lo, hi = np.percentile(f.lap_duration_s, [1, 99])
    for c, g in f.assign(fitted=fitted).groupby('compound'):
        ax.scatter(g.lap_duration_s, g.fitted, s=10, alpha=.6, label=c, color={'SOFT': RED, 'MEDIUM': ORANGE, 'HARD': GREY}.get(c, BLUE))
    ax.plot([lo, hi], [lo, hi], color='black', ls='--', lw=1); ax.set_xlim(lo - .5, hi + .5); ax.set_ylim(lo - .5, hi + .5)
    ax.set_xlabel('Actual lap time (s)'); ax.set_ylabel('Fitted lap time (s)'); ax.set_title(f'Ridge calibration fit (in-sample MAE {np.abs(resid).mean():.3f}s)'); ax.legend(title='Compound')
    out.append(save(fig, folder, 'strategy_fitted_vs_actual.png'))
    # 2. Residuals against tyre age, the effect the simulator relies on.
    fig = figure(7.5, 4.5); ax = fig.add_subplot()
    ax.scatter(f.tyre_life, np.clip(resid, -3, 3), s=10, alpha=.5, color=BLUE); ax.axhline(0, color='black', lw=1)
    ax.set_xlabel('Tyre age (laps)'); ax.set_ylabel('Residual (s, clipped to ±3)'); ax.set_title('Residuals vs tyre age (structure here = missed degradation)')
    out.append(save(fig, folder, 'strategy_residuals_vs_tyre_age.png'))
    # 3. Coefficients the simulator uses.
    names = ['Tyre age (s/lap)', 'Lap number / fuel (s/lap)'] + [f'{c} offset (s)' for c in engine.compound_offsets]
    vals = [engine.age_coefficient, engine.fuel_coefficient] + list(engine.compound_offsets.values())
    fig = figure(7, 4); ax = fig.add_subplot(); ax.barh(names, vals, color=[BLUE if v >= 0 else ORANGE for v in vals]); ax.axvline(0, color='black', lw=1)
    ax.set_title(f'Simulator coefficients (pit loss {engine.pit_loss:.1f}s)'); ax.set_xlabel('Seconds')
    out.append(save(fig, folder, 'strategy_coefficients.png'))
    return out


PLOTS = {'pace': pace, 'dna': dna, 'strategy': strategy}


def write(kind, model_dir, engine):
    """Write <model_dir>/images/*.png for this experiment; returns the file names."""
    folder = os.path.join(model_dir, 'images'); os.makedirs(folder, exist_ok=True)
    return PLOTS[kind](folder, engine)
