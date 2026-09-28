/*
 * File: client_version.sql
 * Purpose: Retrieves MySQL server version information
 *
 * This query returns the full version string of the connected MySQL server,
 * including version number, platform, and build information.
 *
 * Returns: Server version string
 *
 * Example output: "8.0.35"
 */
SELECT VERSION();