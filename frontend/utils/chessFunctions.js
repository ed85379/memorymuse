import { Chess } from "chess.js";

const PIECE_NAMES = {
  p: "pawn",
  n: "knight",
  b: "bishop",
  r: "rook",
  q: "queen",
  k: "king",
};

const COLOR_NAMES = {
  w: "White",
  b: "Black",
};

function squareName(square) {
  return square.toUpperCase();
}

export function describeMove(beforeFen, moveInput, expectedAfterFen) {
  const board = new Chess(beforeFen);
  const move = board.move(moveInput); // Throws if invalid.

  if (expectedAfterFen && board.fen() !== expectedAfterFen) {
    throw new Error("Move result does not match committed post-move FEN.");
  }

  const side = COLOR_NAMES[move.color];
  const enemy = COLOR_NAMES[move.color === "w" ? "b" : "w"];
  const piece = PIECE_NAMES[move.piece];

  let text;

  if (move.isKingsideCastle()) {
    text = `${side} castled kingside.`;
  } else if (move.isQueensideCastle()) {
    text = `${side} castled queenside.`;
  } else if (move.isBigPawn()) {
    text =
      `${side} pawn advanced two squares, from ${squareName(move.from)} ` +
      `to ${squareName(move.to)}.`;
  } else {
    text =
      `${side} ${piece} moved from ${squareName(move.from)} ` +
      `to ${squareName(move.to)}`;

    if (move.isCapture() || move.isEnPassant()) {
      const capturedPiece = PIECE_NAMES[move.captured ?? "p"];
      text += ` and captured ${enemy}'s ${capturedPiece}`;

      if (move.isEnPassant()) {
        text += " en passant";
      }
    }

    if (move.isPromotion()) {
      text += ` and promoted to a ${PIECE_NAMES[move.promotion]}`;
    }

    text += ".";
  }

  if (board.isCheckmate()) {
    text += " Checkmate.";
  } else if (board.isStalemate()) {
    text += " Stalemate.";
  } else if (board.inCheck()) {
    text += ` ${COLOR_NAMES[board.turn()]} is in check.`;
  }

  return {
    narration: text,
    san: move.san,
    lan: move.lan,
    before_fen: move.before,
    after_fen: move.after,

    move: {
      color: move.color,
      piece: move.piece,
      from: move.from,
      to: move.to,
      captured: move.captured ?? null,
      promotion: move.promotion ?? null,
      is_capture: move.isCapture() || move.isEnPassant(),
      is_en_passant: move.isEnPassant(),
      is_castle: move.isKingsideCastle() || move.isQueensideCastle(),
      is_big_pawn: move.isBigPawn(),
      gives_check: board.inCheck(),
      is_checkmate: board.isCheckmate(),
      is_stalemate: board.isStalemate(),
    },
  };
}