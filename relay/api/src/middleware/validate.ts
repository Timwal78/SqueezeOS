import { Request, Response, NextFunction } from "express";

// XRPL classic address validation
const XRPL_ADDRESS_RE = /^r[1-9A-HJ-NP-Za-km-z]{24,33}$/;

export function validateAddress(
  field: string,
  optional = false
): (req: Request, res: Response, next: NextFunction) => void {
  return (req, res, next) => {
    const value = req.body?.[field] ?? req.params?.[field] ?? req.query?.[field];
    if (!value && optional) return next();
    if (!value || !XRPL_ADDRESS_RE.test(String(value))) {
      res.status(400).json({
        error: `Invalid XRPL address for field '${field}'`,
        code: "INVALID_ADDRESS",
      });
      return;
    }
    next();
  };
}

export function requireFields(
  ...fields: string[]
): (req: Request, res: Response, next: NextFunction) => void {
  return (req, res, next) => {
    const missing = fields.filter(
      (f) => req.body?.[f] === undefined || req.body?.[f] === null || req.body?.[f] === ""
    );
    if (missing.length) {
      res.status(400).json({
        error: `Missing required fields: ${missing.join(", ")}`,
        code: "MISSING_FIELDS",
        fields: missing,
      });
      return;
    }
    next();
  };
}

export function errorHandler(
  err: Error & { code?: string; status?: number },
  req: Request,
  res: Response,
  next: NextFunction
): void {
  const status = err.status ?? 500;
  const code = err.code ?? "INTERNAL_ERROR";

  if (process.env.NODE_ENV !== "production") {
    console.error(`[${code}] ${err.message}`, err.stack);
  }

  res.status(status).json({
    error: err.message ?? "Internal server error",
    code,
  });
}
