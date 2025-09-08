async function getCoinGeckoPrice() {
    try {
        const res = await fetch("https://api.coingecko.com/api/v3/simple/price?ids=ethereum&vs_currencies=usd");
        const data = await res.json();
        return data.ethereum.usd;
    } catch (err) {
        console.error("CoinGecko API error:", err.message);
        return null;
    }
}

async function main() {
    let ethprice = await Promise.resolve(getCoinGeckoPrice());
    console.log("ETH", ethprice);
}

main();
