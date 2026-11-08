export const GANESHA_WILD_SYMBOL = 'WILD_GANESHA';

/** Derive the only permitted display board from the immutable raw stopped board. */
export function deriveExpandedWildDisplayBoard(rawBoard, expandedWildReels) {
  if (!Array.isArray(rawBoard) || rawBoard.length !== 5
      || rawBoard.some((reel) => !Array.isArray(reel) || reel.length !== 3
        || reel.some((symbol) => typeof symbol !== 'string' || symbol.length === 0))) {
    throw new TypeError('raw board must be a 5x3 matrix of non-empty symbol strings');
  }
  if (!Array.isArray(expandedWildReels)) {
    throw new TypeError('expanded Wild reel indices must be an array');
  }
  const selected = new Set();
  for (const reelIndex of expandedWildReels) {
    if (!Number.isSafeInteger(reelIndex) || reelIndex < 0 || reelIndex >= 5 || selected.has(reelIndex)) {
      throw new TypeError('expanded Wild reel indices must be unique integers from 0 through 4');
    }
    if (!rawBoard[reelIndex].includes(GANESHA_WILD_SYMBOL)) {
      throw new TypeError('expanded Wild reel must contain an original WILD_GANESHA symbol');
    }
    selected.add(reelIndex);
  }
  return rawBoard.map((reel, reelIndex) => selected.has(reelIndex)
    ? [GANESHA_WILD_SYMBOL, GANESHA_WILD_SYMBOL, GANESHA_WILD_SYMBOL]
    : [...reel]);
}
