# Test Plan

## Formula tests
- clamp and normalization bounds
- argus strength increases with confidence and stable structure
- echo strength decreases when failure probability rises
- liquidity strength collapses when sweep probabilities are balanced
- truth-adjusted strength collapses under high deception

## Fusion tests
- full alignment + low deception -> high omega
- high deception + bullish alignment -> action_class should not be aggressive
- mixed conflict -> observe_only or watch_trigger
- failed_breakout_trap dominant -> do_not_chase
- watch_for_sweep should set sweep_target and confirmation_mode
